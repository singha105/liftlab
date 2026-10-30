-- The activation funnel for new users with at least 7 full days of data:
--   1 app_opened         first open (everyone in the cohort)
--   2 session_started    a session started within 24 h of the first open
--   3 session_completed  a session completed within 24 h of the first open (activated)
--   4 second_session_7d  another session started after that first completion, within
--                        7 days of the first open
-- Each step is a subset of the one before it.
create or replace table funnel_activation as
with cohort as (
    select u.source, u.user_id, u.first_opened_at, u.activated_at
    from dim_users u
    join warehouse_meta m on m.source = u.source
    where u.first_opened_at is not null
      and u.first_opened_at + interval 7 day <= m.data_end
),
reached as (
    select
        c.source,
        c.user_id,
        coalesce(bool_or(s.started_at < c.first_opened_at + interval 24 hour), false) as started,
        c.activated_at is not null as completed,
        coalesce(
            bool_or(
                s.started_at > c.activated_at
                and s.started_at < c.first_opened_at + interval 7 day
            ),
            false
        ) as came_back
    from cohort c
    left join fct_sessions s
        on s.source = c.source and s.user_id = c.user_id and s.started_at >= c.first_opened_at
    group by c.source, c.user_id, c.activated_at
),
steps as (
    select source, 1 as step_number, 'app_opened' as step, count(*) as users
    from reached group by source
    union all
    select source, 2, 'session_started', count(*) filter (where started)
    from reached group by source
    union all
    select source, 3, 'session_completed', count(*) filter (where completed)
    from reached group by source
    union all
    select source, 4, 'second_session_7d', count(*) filter (where completed and came_back)
    from reached group by source
)
select
    source,
    step_number,
    step,
    users,
    users / coalesce(lag(users) over w, users) as step_conversion,
    users / first_value(users) over w as overall_conversion,
    coalesce(lag(users) over w - users, 0) as drop_off
from steps
window w as (partition by source order by step_number)
order by source, step_number;
