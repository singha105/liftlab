-- D1, D7 and D28 retention by weekly acquisition cohort.
-- Dn is the share of the cohort with a session started on day n exactly (UTC calendar days
-- after day 0). The denominator is every new user, activated or not. A cohort's Dn is only
-- reported once its last member's day n has ended, so no rate here is from a partial period.
create or replace table retention_cohorts as
with active_days as (
    select distinct source, user_id, started_date from fct_sessions
),
members as (
    select
        u.source,
        u.acquisition_week,
        coalesce(bool_or(a.started_date = u.acquisition_date + 1), false) as d1,
        coalesce(bool_or(a.started_date = u.acquisition_date + 7), false) as d7,
        coalesce(bool_or(a.started_date = u.acquisition_date + 28), false) as d28
    from dim_users u
    left join active_days a on a.source = u.source and a.user_id = u.user_id
    where u.first_opened_at is not null
    group by u.source, u.user_id, u.acquisition_week
),
cohorts as (
    select
        source,
        acquisition_week as cohort_week,
        count(*) as cohort_users,
        count(*) filter (where d1) as d1_users,
        count(*) filter (where d7) as d7_users,
        count(*) filter (where d28) as d28_users
    from members
    group by source, acquisition_week
)
select
    c.source,
    c.cohort_week,
    c.cohort_users,
    -- the cohort's last day 0 is cohort_week + 6, so its day n ends at cohort_week + 7 + n
    case when c.cohort_week + interval 8 day <= m.data_end then c.d1_users end as d1_users,
    case when c.cohort_week + interval 8 day <= m.data_end
        then c.d1_users / c.cohort_users end as d1_retention,
    case when c.cohort_week + interval 14 day <= m.data_end then c.d7_users end as d7_users,
    case when c.cohort_week + interval 14 day <= m.data_end
        then c.d7_users / c.cohort_users end as d7_retention,
    case when c.cohort_week + interval 35 day <= m.data_end then c.d28_users end as d28_users,
    case when c.cohort_week + interval 35 day <= m.data_end
        then c.d28_users / c.cohort_users end as d28_retention
from cohorts c
join warehouse_meta m on m.source = c.source
order by c.source, c.cohort_week;
