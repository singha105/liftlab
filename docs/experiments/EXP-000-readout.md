# EXP-000 Cookie Cats gate at level 40: KILL

**REAL: Cookie Cats mobile game A/B test, public Kaggle data, N = 90,189**

- **SRM**: p = 0.0086 (ok) | users 44,700 gate_30 / 45,489 gate_40
- **Primary, 7-day retention**: 19.0% → 18.2% | -0.8pp [-1.3pp, -0.3pp] (-4.3% relative) | p = 0.0016
  - Bootstrap, difference in means: 19.0% → 18.2% | -0.8pp [-1.4pp, -0.3pp] (2,000 resamples of users)
- **Guardrail, Players who never played a round**: 4.3% → 4.5% | +0.2pp [-0.1pp, +0.5pp] (threshold +1.0pp) ok
- **Secondary, 1-day retention**: 44.8% → 44.2% | -0.6pp [-1.2pp, +0.1pp] (-1.3% relative) | p = 0.07, Holm-adjusted p = 0.15
  - Bootstrap, difference in means: 44.8% → 44.2% | -0.6pp [-1.2pp, +0.1pp] (2,000 resamples of users)
- **Secondary, Game rounds in the first 14 days**: 52.46 → 51.30 | -1.16 [-3.72, +1.40] (-2.2% relative) | p = 0.38, Holm-adjusted p = 0.38
  - Bootstrap, difference in medians: 17.00 → 16.00 | -1.00 [-1.00, +0.00] (2,000 resamples of users)

**Decision: KILL, keep the gate at level 30**

- Not INVALID: no sample ratio mismatch (p = 0.0086)
- Not UNDERPOWERED: both arms reached 24,641 users
- Not KILL: no guardrail regressed beyond its threshold
- Not SHIP: 7-day retention CI [-1.3pp, -0.3pp] includes or is below 0
- Not ITERATE: 7-day retention point estimate -0.8pp is below half the MDE (+0.5pp)

## Outliers: game rounds over 10,000

Game rounds have a long tail: the 99th percentile is 493 and the 99.9th 1,074. 1 player went over the 10,000-round cap; the largest total under it is 2,961.

| Player | Arm | Rounds in 14 days | Per day | Back on day 1 | Back on day 7 |
|---|---|---|---|---|---|
| 6390605 | gate_30 | 49,854 | 3,561 | no | yes |

Welch's t-test on game rounds, test − control:

- Everyone (analysis of record): 52.46 → 51.30, -1.16 [-3.72, +1.40], p = 0.38
- Without the 1 over the cap (sensitivity only): 51.34 → 51.30, -0.04 [-1.38, +1.30], p = 0.95

## Why there's no CUPED

Every player was randomized at install, so there's no behavior from before the experiment to adjust with. Game rounds and 1-day retention are measured after assignment and can be changed by the gate, so adjusting for them would bias the estimate. The file has no pre-assignment attribute (device, country, install source) for a regression adjustment either. The readout is unadjusted.

*REAL: Cookie Cats mobile game A/B test, public Kaggle data, N = 90,189*
