-- One row per real, planned event, with its properties as typed columns.
-- Drops duplicate deliveries (same uuid), demo traffic (is_demo) and anything not in
-- docs/TRACKING_PLAN.md. Timestamps are UTC; weeks are ISO weeks starting Monday.
create or replace table stg_events as
with planned as (
    select
        source,
        coalesce(
            uuid,
            md5(concat_ws('|', distinct_id, event, timestamp::varchar, properties::varchar))
        ) as event_id,
        distinct_id as user_id,
        event,
        timestamp as ts,
        properties
    from raw_events
    where event in (
        'app_opened', 'session_started', 'session_completed', 'session_abandoned',
        'streak_viewed', 'weekly_summary_viewed', 'experiment_exposed'
    )
      and distinct_id is not null
    qualify row_number() over (partition by source, event_id order by ts) = 1
)
select
    source,
    event_id,
    user_id,
    event,
    ts,
    ts::date as event_date,
    date_trunc('week', ts)::date as event_week,
    -- on every event
    properties ->> 'app_version' as app_version,
    properties ->> 'experiment_key' as experiment_key,
    properties ->> 'variant' as variant,
    properties ->> '$."$device_type"' as device_type,
    -- app_opened
    try_cast(properties ->> 'is_first_open' as boolean) as is_first_open,
    try_cast(properties ->> 'load_ms' as integer) as load_ms,
    properties ->> 'referrer_type' as referrer_type,
    -- sessions
    properties ->> 'session_id' as session_id,
    try_cast(properties ->> 'planned_minutes' as integer) as planned_minutes,
    try_cast(properties ->> 'goal_set' as boolean) as goal_set,
    properties ->> 'start_method' as start_method,
    try_cast(properties ->> 'session_number' as integer) as session_number,
    try_cast(properties ->> 'actual_minutes' as integer) as actual_minutes,
    try_cast(properties ->> 'pause_count' as integer) as pause_count,
    try_cast(properties ->> 'is_first_completion' as boolean) as is_first_completion,
    try_cast(properties ->> 'completed_while_away' as boolean) as completed_while_away,
    try_cast(properties ->> 'elapsed_seconds' as integer) as elapsed_seconds,
    properties ->> 'reason' as reason,
    -- streak and weekly summary
    try_cast(properties ->> 'current_streak_days' as integer) as current_streak_days,
    try_cast(properties ->> 'longest_streak_days' as integer) as longest_streak_days,
    properties ->> 'surface' as surface,
    try_cast(properties ->> 'sessions_completed_week' as integer) as sessions_completed_week,
    try_cast(properties ->> 'focus_minutes_week' as integer) as focus_minutes_week,
    properties ->> 'opened_by' as opened_by
from planned
where not coalesce(try_cast(properties ->> 'is_demo' as boolean), false);
