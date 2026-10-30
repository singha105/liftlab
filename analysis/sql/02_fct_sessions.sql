-- One row per session: its session_started joined to its first end event.
-- A session with no end event 24 hours after it started counts as abandoned, reason
-- no_end_event (docs/TRACKING_PLAN.md, session lifecycle). One younger than that at the
-- data cutoff is still 'open' and stays out of completion and abandon rates.
create or replace table fct_sessions as
with starts as (
    select
        source, user_id, session_id, ts as started_at, planned_minutes, goal_set,
        start_method, session_number, experiment_key, variant
    from stg_events
    where event = 'session_started' and session_id is not null
    qualify row_number() over (partition by source, session_id order by ts) = 1
),
ends as (
    select
        source, session_id, event, ts as ended_at, actual_minutes, elapsed_seconds,
        pause_count, reason, completed_while_away
    from stg_events
    where event in ('session_completed', 'session_abandoned') and session_id is not null
    qualify row_number() over (partition by source, session_id order by ts) = 1
)
select
    s.source,
    s.user_id,
    s.session_id,
    s.started_at,
    s.started_at::date as started_date,
    date_trunc('week', s.started_at)::date as started_week,
    e.ended_at,
    e.ended_at::date as ended_date,
    date_trunc('week', e.ended_at)::date as ended_week,
    case
        when e.event = 'session_completed' then 'completed'
        when e.event = 'session_abandoned' then 'abandoned'
        when s.started_at + interval 24 hour <= m.data_end then 'abandoned'
        else 'open'
    end as outcome,
    case
        when e.event = 'session_abandoned' then e.reason
        when e.event is null and s.started_at + interval 24 hour <= m.data_end then 'no_end_event'
    end as abandon_reason,
    s.planned_minutes,
    s.goal_set,
    s.start_method,
    s.session_number,
    e.actual_minutes,
    e.pause_count,
    e.elapsed_seconds,
    coalesce(e.completed_while_away, false) as completed_while_away,
    case
        when e.event = 'session_completed' then s.planned_minutes::double
        when e.event = 'session_abandoned' then e.elapsed_seconds / 60.0
    end as focus_minutes,
    s.experiment_key,
    s.variant
from starts s
join warehouse_meta m on m.source = s.source
left join ends e on e.source = s.source and e.session_id = s.session_id;
