# 0004: Read the primary once at a fixed N; use the mSPRT only to monitor

- Status: accepted
- Date: 2026-10-31
- Decider: Arnab Singh
- Recorded: 2026-11-01, from the Day 5 and Day 6 logs in [PROGRESS.md](../PROGRESS.md) and EXP-001's [amendments](../experiments/EXP-001.md#amendments)

## Context

EXP-001's plan reads activation once, at 1,377 users per arm, and checks SRM and the guardrails every week. Anyone watching a dashboard will be tempted to look at activation sooner. The Day 5 peeking proof measured what that costs: across 1,000 simulated A/A experiments checked daily for 28 days, stopping at the first p < 0.05 from a fixed-horizon z-test declared a false win 27.3% of the time. An mSPRT (Johari, Pekelis and Walsh) on the same experiments stopped 1.7% of the time (synthetic).

## Options considered

1. Fixed-horizon z-test, read once at the planned N, with no early stopping.
2. An mSPRT for the primary, so it can be watched and stopped at any time.
3. A fixed-horizon read for the primary, and mSPRT confidence sequences for the weekly guardrail checks.

## Decision

Option 3. Activation is read once, with the pre-registered z-test, at 1,377 per arm or the 8-week limit. Each week, SRM is checked and each guardrail is followed as an mSPRT 95% confidence sequence, with the guardrail's own threshold as the mixing sd. The run stops early only for an SRM failure or a guardrail whose always-valid interval lies entirely past its threshold ([Amendment 1](../experiments/EXP-001.md#1-2026-10-31-before-launch-how-the-weekly-checks-use-the-sequential-test)). Interim reads of activation are descriptive and can't decide anything ([Amendment 2](../experiments/EXP-001.md#2-2026-10-31-before-launch-interim-reads)).

## Why

- The sample size was computed for a fixed-horizon test. An mSPRT primary would need a larger N for the same power, and N is already out of reach.
- The mSPRT's guarantee holds for any number of looks, so with weekly looks it's conservative: it trades power for safety. That's the right trade for guardrails, which can stop a harmful run, and the wrong one for the metric we hope to ship on.
- A guardrail's point estimate would be checked about 8 times over a run, so on its own it would raise false alarms. The always-valid interval doesn't.

## Consequences

- No early win. Even a large activation lift waits for the read.
- The weekly checks only catch large regressions. In six simulated weeks the abandon-rate interval stayed about ±3.5 points wide, so stopping early needs a true regression of about +5.5 points. Smaller ones wait for the read, where rule 3 judges the point estimate.
- Both amendments were dated before launch, and neither changed the primary metric, the read or the decision rule.

## Revisit if

- Traffic grows enough that stopping early for a win is worth the extra users an mSPRT primary needs. That change would be a new pre-registration, not an amendment.
