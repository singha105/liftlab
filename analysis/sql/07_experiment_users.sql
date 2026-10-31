-- One row per user per experiment they were exposed to: what the readout analyzes
-- (docs/experiments/EXP-001.md). Windows are anchored at the first exposure, which for new
-- users is their first page load, so "7 days after exposure" is "7 days after first open".
-- - Arm: the variant on the first experiment_exposed. Users seen in more than one arm are
--   kept with variants > 1, and the readout drops and counts them.
-- - Sessions started in the 7 days from exposure, by outcome. Ended = completed + abandoned,
--   so a session still open at the cutoff counts in neither the abandon rate nor its base.
-- - pre_sessions_28d: sessions started in the 28 days before exposure, the CUPED covariate.
-- - Device and referrer of the page load the user was exposed on, fixed before assignment.
-- - load_ms_7d: load times of later page loads within 7 days. The exposure load itself is
--   measured before the flag arrives, so it can't differ by arm.
create or replace table experiment_users as
with exposures as (
    select
        source,
        user_id,
        experiment_key,
        min(ts) as exposed_at,
        arg_min(variant, ts) as variant,
        count(distinct variant) as variants
    from stg_events
    where event = 'experiment_exposed' and coalesce(experiment_key, 'none') <> 'none'
    group by source, user_id, experiment_key
),
exposure_load as (
    select
        x.source,
        x.user_id,
        x.experiment_key,
        arg_max(o.device_type, o.ts) as device_type,
        arg_max(o.referrer_type, o.ts) as referrer_type,
        count(*) as opens_through_exposure
    from exposures x
    join stg_events o
        on o.source = x.source and o.user_id = x.user_id
        and o.event = 'app_opened' and o.ts <= x.exposed_at
    group by x.source, x.user_id, x.experiment_key
),
sessions as (
    select
        x.source,
        x.user_id,
        x.experiment_key,
        count(*) filter (where s.started_at >= x.exposed_at) as started_sessions_7d,
        count(*) filter (where s.started_at >= x.exposed_at and s.outcome = 'completed')
            as completed_sessions_7d,
        count(*) filter (where s.started_at >= x.exposed_at and s.outcome = 'abandoned')
            as abandoned_sessions_7d,
        count(*) filter (where s.started_at < x.exposed_at) as pre_sessions_28d
    from exposures x
    join fct_sessions s
        on s.source = x.source and s.user_id = x.user_id
        and s.started_at >= x.exposed_at - interval 28 day
        and s.started_at < x.exposed_at + interval 7 day
    group by x.source, x.user_id, x.experiment_key
),
loads as (
    select
        x.source,
        x.user_id,
        x.experiment_key,
        list(o.load_ms order by o.ts) as load_ms_7d
    from exposures x
    join stg_events o
        on o.source = x.source and o.user_id = x.user_id
        and o.event = 'app_opened' and o.load_ms is not null
        and o.ts > x.exposed_at and o.ts < x.exposed_at + interval 7 day
    group by x.source, x.user_id, x.experiment_key
)
select
    x.source,
    x.experiment_key,
    x.user_id,
    x.variant,
    x.variants,
    x.exposed_at,
    u.first_opened_at,
    e.opens_through_exposure = 1 as new_at_exposure,
    u.activated_at is not null as activated,
    u.activation_window_closed,
    -- Sessions started up to day 7 get 24 hours to end before they count as abandoned.
    x.exposed_at + interval 8 day <= m.data_end as window_7d_closed,
    coalesce(s.started_sessions_7d, 0) as started_sessions_7d,
    coalesce(s.completed_sessions_7d, 0) as completed_sessions_7d,
    coalesce(s.abandoned_sessions_7d, 0) as abandoned_sessions_7d,
    coalesce(s.completed_sessions_7d, 0) + coalesce(s.abandoned_sessions_7d, 0)
        as ended_sessions_7d,
    coalesce(s.pre_sessions_28d, 0) as pre_sessions_28d,
    e.device_type,
    e.referrer_type,
    coalesce(l.load_ms_7d, []::integer[]) as load_ms_7d
from exposures x
join warehouse_meta m on m.source = x.source
join dim_users u on u.source = x.source and u.user_id = x.user_id
left join exposure_load e
    on e.source = x.source and e.user_id = x.user_id and e.experiment_key = x.experiment_key
left join sessions s
    on s.source = x.source and s.user_id = x.user_id and s.experiment_key = x.experiment_key
left join loads l
    on l.source = x.source and l.user_id = x.user_id and l.experiment_key = x.experiment_key;
