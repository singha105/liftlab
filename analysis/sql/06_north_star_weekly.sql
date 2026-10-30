-- The North Star and every input from the metric tree, one row per complete ISO week.
-- weekly_completed_sessions counts completions in the week they happened. Completion and
-- abandon rates count sessions in the week they started, leaving out sessions still open at
-- the cutoff. So wau * sessions_per_active_user * completion_rate (wcs_from_identity) equals
-- completed sessions by start week, which differs from the North Star only by sessions that
-- ran across midnight on a Sunday (docs/METRICS.md, metric tree).
create or replace table north_star_weekly as
with bounds as (
    select
        m.source,
        date_trunc('week', min(e.ts)) as first_week,
        m.data_end
    from warehouse_meta m
    join stg_events e on e.source = m.source
    group by m.source, m.data_end
),
weeks as (
    select source, data_end, unnest(generate_series(first_week, data_end, interval 7 day)) as week
    from bounds
),
complete_weeks as (
    select source, week::date as week_start, data_end
    from weeks
    where week + interval 7 day <= data_end
),
completed as (
    select
        source,
        ended_week as week_start,
        count(*) as weekly_completed_sessions,
        sum(planned_minutes) as weekly_focus_minutes
    from fct_sessions
    where outcome = 'completed'
    group by source, ended_week
),
started as (
    select
        source,
        started_week as week_start,
        count(*) as sessions_started,
        count(distinct user_id) as wau,
        count(*) filter (where outcome = 'completed') as completed_of_started,
        count(*) filter (where outcome = 'abandoned') as abandoned_of_started,
        count(*) filter (where outcome <> 'open') as ended_of_started,
        avg(goal_set::int) as goal_set_rate,
        avg((planned_minutes = 15)::int) as share_15_min,
        avg((planned_minutes = 25)::int) as share_25_min,
        avg((planned_minutes = 50)::int) as share_50_min
    from fct_sessions
    group by source, started_week
),
daily as (
    select source, date_trunc('week', started_date)::date as week_start, count(distinct user_id) as dau
    from fct_sessions
    group by source, started_date
),
active_days as (
    select source, week_start, sum(dau) as user_days from daily group by source, week_start
),
first_week as (
    select source, user_id, min(started_week) as first_active_week
    from fct_sessions
    group by source, user_id
),
returners as (
    select s.source, s.started_week as week_start, count(distinct s.user_id) as returning_users
    from fct_sessions s
    join first_week f on f.source = s.source and f.user_id = s.user_id
    where f.first_active_week < s.started_week
    group by s.source, s.started_week
),
acquired as (
    select
        source,
        acquisition_week as week_start,
        count(*) as new_users,
        count(*) filter (where activated_at is not null) as activated_users
    from dim_users
    where first_opened_at is not null
    group by source, acquisition_week
),
viewed as (
    select
        source,
        event_week as week_start,
        count(*) filter (where event = 'streak_viewed') as streak_views,
        count(*) filter (where event = 'weekly_summary_viewed') as weekly_summary_views,
        quantile_cont(load_ms, 0.75) filter (where event = 'app_opened') as load_ms_p75,
        count(*) as events
    from stg_events
    group by source, event_week
),
per_user as (  -- completions per active user, for concentration
    select s.source, s.week_start, s.user_id, coalesce(c.completions, 0) as completions
    from (select distinct source, started_week as week_start, user_id from fct_sessions) s
    left join (
        select source, ended_week as week_start, user_id, count(*) as completions
        from fct_sessions
        where outcome = 'completed'
        group by source, ended_week, user_id
    ) c on c.source = s.source and c.week_start = s.week_start and c.user_id = s.user_id
),
concentration as (
    select
        source,
        week_start,
        sum(completions) filter (where position <= ceil(0.1 * users)) / nullif(sum(completions), 0)
            as top_decile_share
    from (
        select
            *,
            row_number() over (partition by source, week_start order by completions desc) as position,
            count(*) over (partition by source, week_start) as users
        from per_user
    )
    group by source, week_start
)
select
    w.source,
    w.week_start,
    -- North Star
    coalesce(c.weekly_completed_sessions, 0) as weekly_completed_sessions,
    -- its exact factors
    coalesce(s.wau, 0) as wau,
    coalesce(s.sessions_started, 0) as sessions_started,
    s.sessions_started / nullif(s.wau, 0) as sessions_per_active_user,
    s.completed_of_started / nullif(s.ended_of_started, 0) as completion_rate,
    s.sessions_started * s.completed_of_started / nullif(s.ended_of_started, 0)
        as wcs_from_identity,
    -- drivers of WAU
    coalesce(a.new_users, 0) as new_users,
    case when w.week_start + interval 8 day <= w.data_end
        then a.activated_users / nullif(a.new_users, 0) end as activation_rate,
    coalesce(s.wau, 0) - coalesce(r.returning_users, 0) as new_active_users,
    coalesce(r.returning_users, 0) as returning_users,
    v.streak_views / nullif(s.wau, 0) as streak_views_per_active_user,
    -- drivers of sessions per active user
    d.user_days / 7.0 / nullif(s.wau, 0) as active_days_per_week,
    coalesce(v.weekly_summary_views, 0) as weekly_summary_views,
    -- drivers of completion rate
    s.goal_set_rate,
    s.share_15_min,
    s.share_25_min,
    s.share_50_min,
    -- guardrails
    s.abandoned_of_started / nullif(s.ended_of_started, 0) as abandon_rate,
    v.load_ms_p75,
    -- health
    coalesce(c.weekly_focus_minutes, 0) as weekly_focus_minutes,
    k.top_decile_share,
    coalesce(v.events, 0) as event_volume
from complete_weeks w
left join completed c on c.source = w.source and c.week_start = w.week_start
left join started s on s.source = w.source and s.week_start = w.week_start
left join active_days d on d.source = w.source and d.week_start = w.week_start
left join returners r on r.source = w.source and r.week_start = w.week_start
left join acquired a on a.source = w.source and a.week_start = w.week_start
left join viewed v on v.source = w.source and v.week_start = w.week_start
left join concentration k on k.source = w.source and k.week_start = w.week_start
order by w.source, w.week_start;
