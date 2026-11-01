# EXP-001 interim readout, 2026-10-31

Two reads of EXP-001, kept apart and labeled by where their users came from. Neither one decides anything: the live run hasn't launched, and the simulated one only shows what a full-size read looks like. Interim reads are covered by [Amendment 2](EXP-001.md#2-2026-10-31-before-launch-interim-reads).

## REAL: StudySprint live data, N = 0

From `uv run liftlab readout --source posthog --interim`:

```
# EXP-001 Quick Start: interim read, not a decision

**REAL: StudySprint live data, N = 0, underpowered (needs 1,377 per arm)**

- **Exposed users**: 0 control / 0 test, against the 1,377 per arm the read needs
- **Power**: none yet; with no users the test can't detect +5.0pp.

Underpowered means a result here can't be acted on either way. Not significant says almost nothing about whether the change works, and significant would most likely overstate the lift, since only large estimates clear the bar at this size. The decision rule calls any read before the required N UNDERPOWERED.

*REAL: StudySprint live data, N = 0, underpowered (needs 1,377 per arm)*
```

**Why zero.** The live site has no PostHog project key yet (the `VITE_POSTHOG_KEY` repository variable isn't set), so it sends no events. There's no personal API key in `.env` either, so `uv run liftlab export-posthog` stops with "skipping the PostHog export: POSTHOG_PROJECT_ID and POSTHOG_PERSONAL_API_KEY not set in .env". The experiment hasn't launched.

**What underpowered means here, plainly.** Even once events flow, StudySprint gets about 5 eligible new users a day, so the 8-week cap ends near 140 users per arm. At 140 per arm:

- the test detects the planned +5.0-point lift only **14.5%** of the time;
- the smallest lift it would catch 80% of the time is **16.2 points**, activation going from 30% to about 46%.

So the live read will almost certainly be UNDERPOWERED, and the product stays on control. A non-significant result won't mean Quick Start doesn't work. A significant one would most likely overstate the lift, because at this size only large estimates clear the bar. The live run's job is the plumbing: a fair split, one exposure per user, Quick Start sessions tagged `quick_start`, and the export reaching the warehouse.

## SYNTHETIC: a full-size simulated run

3,581 simulated new users over two weeks, enough for both arms to reach 1,377, with a true activation effect of **+5.0 points** on a true control rate of 30.69%. Seed 4 is the example already in the Day 5 log, not one picked for this page. From:

```bash
uv run liftlab --db /tmp/exp001.duckdb load --source synthetic --users 3581 --weeks 2 --seed 4 --experiment exp-001 --experiment-start-day 0 --audience new --activation-effect 0.05
uv run liftlab --db /tmp/exp001.duckdb build
uv run liftlab --db /tmp/exp001.duckdb readout --source synthetic
```

```
# EXP-001 Quick Start: SHIP

**SYNTHETIC: simulated users with known ground truth, not real usage**

- **SRM**: p = 0.80 (ok) | users 1,377 control / 1,390 test
- **Primary, Activation rate**: 28.5% → 38.4% | +9.9pp [+6.5pp, +13.4pp] (+35.0% relative) | p < 0.0001
  - Regression-adjusted for device type and referrer (sensitivity only): +9.8pp [+6.3pp, +13.3pp], variance ±0%
- **Guardrail, Abandon rate**: 31.4% → 31.0% | -0.3pp [-3.2pp, +2.6pp] (threshold +2.0pp) ok
- **Guardrail, Page load p75**: 671 → 682 ms | +1.6% [-4.8%, +7.9%] (threshold +10% or 2,000 ms) ok
- **Secondary, Completed sessions per user in 7 days**: 1.19 → 1.52 | +0.33 [+0.17, +0.49] (+28.0% relative) | p < 0.0001, Holm-adjusted p < 0.0001

**Decision: SHIP**

- Not INVALID: no sample ratio mismatch (p = 0.80)
- Not UNDERPOWERED: both arms reached 1,377 users
- Not KILL: no guardrail regressed beyond its threshold
- Activation rate CI [+6.5pp, +13.4pp] is entirely above 0
- No secondary metric is significantly worse

*SYNTHETIC: simulated users with known ground truth, not real usage*
```

The estimate, +9.9 points, is a high draw against the true +5.0, and its interval misses the truth. Over 40 seeds of the same setup the readout's mean estimate was +5.12 points and 36 of 40 intervals covered +5.0 ([Day 5 log](../PROGRESS.md)). What this run shows is the method working end to end at the planned N, not how well Quick Start works: that answer needs real users.
