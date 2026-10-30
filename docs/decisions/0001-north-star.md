# 0001: North Star is weekly completed sessions

- Status: accepted
- Date: 2026-10-29
- Decider: Arnab Singh

## Context

StudySprint needs one number that says whether the product is getting better at its job, which is helping students start and finish focused study. Every other metric in the tree should help explain changes in it. v1 has no revenue and no accounts, so the number has to come from anonymous product events.

## Options considered

1. Weekly active users (opened the app)
2. Weekly focus minutes (minutes of completed sessions)
3. Weekly completed sessions

The scoring table is in [METRICS.md](../METRICS.md#how-we-chose-it).

## Decision

The North Star is **weekly completed sessions (WCS)**: the count of `session_completed` events per ISO week, in UTC.

## Why

- A completed session is the unit of value. The student said "I'll focus for 25 minutes" and did it. An opened tab proves nothing, and focus minutes rewards length over follow-through.
- It leads retention through the streak. The streak only grows on days with a completion, and the streak is the main reason to come back.
- It decomposes exactly: WCS = WAU × sessions started per active user × completion rate. Any experiment can say which factor it's trying to move, and readouts can show where a change came from.
- It moves within a week, which suits a build where experiments run for days, not quarters.

## Consequences

- Session length becomes something people could game: shorter sessions mean more completions. v1 only offers 15, 25 and 50 minutes, so no session is shorter than 15, and the length mix is tracked as a health metric.
- Heavy users count for more than light ones. A student who does four sessions a day adds four times as much as one who does one. We're fine with that while it reflects real study, and we track concentration so we notice if it doesn't.
- Weekly focus minutes stays on the dashboard as a health metric, so we can still see whether total focus time is going up.
- Every experiment's pre-registration has to name the input it targets: WAU, sessions per active user or completion rate.

## Revisit if

- The top 10% of users produce more than half of WCS for four weeks running. Then switch to **weekly focused students** (users with at least two completed sessions in the week), which counts how many people the product helps, not how often.
- Real usage data shows week-1 completions predict D28 retention no better than week-1 app opens. Synthetic data can't answer this, because the generator is built on the same assumption.
- More than half of completed sessions are 15-minute ones for four weeks running.
- A later version adds accounts or a paid tier, which makes revenue-linked metrics measurable.

## Amendments

- **2026-10-30.** Day 2 dropped custom session lengths (it had been 10 to 90 minutes), so the shortest session is now 15 minutes. The farming guard and its revisit trigger above were updated to match. The decision itself is unchanged.
