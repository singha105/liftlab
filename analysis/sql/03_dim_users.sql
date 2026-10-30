-- One row per user (anonymous distinct_id) with acquisition, activation and experiment arm.
-- A user is new on the UTC date of their first app_opened (day 0). They're activated if a
-- session_completed lands within 24 hours of that first app_opened (docs/METRICS.md).
create or replace table dim_users as
with seen as (
    select
        source,
        user_id,
        min(ts) as first_seen_at,
        max(ts) as last_seen_at,
        min(ts) filter (where event = 'app_opened') as first_opened_at
    from stg_events
    group by source, user_id
),
sessions as (
    select
        source,
        user_id,
        count(*) as sessions_started,
        count(*) filter (where outcome = 'completed') as sessions_completed,
        min(started_at) as first_session_at,
        min(ended_at) filter (where outcome = 'completed') as first_completed_at
    from fct_sessions
    group by source, user_id
),
exposures as (  -- first exposure; one experiment runs at a time
    select source, user_id, experiment_key, variant, ts as exposed_at
    from stg_events
    where event = 'experiment_exposed'
    qualify row_number() over (partition by source, user_id order by ts) = 1
)
select
    u.source,
    u.user_id,
    u.first_seen_at,
    u.last_seen_at,
    u.first_opened_at,
    u.first_opened_at::date as acquisition_date,
    date_trunc('week', u.first_opened_at)::date as acquisition_week,
    coalesce(s.sessions_started, 0) as sessions_started,
    coalesce(s.sessions_completed, 0) as sessions_completed,
    s.first_session_at,
    s.first_completed_at,
    case
        when s.first_completed_at < u.first_opened_at + interval 24 hour then s.first_completed_at
    end as activated_at,
    u.first_opened_at + interval 24 hour <= m.data_end as activation_window_closed,
    x.experiment_key,
    x.variant,
    x.exposed_at
from seen u
join warehouse_meta m on m.source = u.source
left join sessions s on s.source = u.source and s.user_id = u.user_id
left join exposures x on x.source = u.source and x.user_id = u.user_id;
