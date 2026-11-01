# EXP-000: Cookie Cats, the first gate at level 40

| | |
|---|---|
| Status | **Retrospective.** Written on 2026-10-31, after the data existed and after I had looked at it (see [What I saw before writing this](#what-i-saw-before-writing-this)). The test itself ran years ago at Tactile Entertainment; this is a re-analysis of their public data. |
| Data | **REAL**: the "Mobile Games A/B Testing – Cookie Cats" dataset on Kaggle, 90,189 players. Saved locally as `data/raw/cookie_cats.csv`, never committed. |
| Config | [EXP-000.yaml](EXP-000.yaml), read by `liftlab cookie-cats` |
| Owner | Arnab Singh |

LiftLab's own experiment, [EXP-001](EXP-001.md), can't reach its sample size on StudySprint's traffic. Cookie Cats is the library's first real data at scale: one row per player, randomized at install, with no events to rebuild. It's EXP-000 because it isn't StudySprint's.

## What I saw before writing this

A real pre-registration is written before anyone sees the outcome. This one wasn't, so it can't prove the plan wasn't fitted to the result. Here is everything I knew when I wrote it:

- This dataset is a well-known teaching example, and I knew its usual conclusion before opening the file: 7-day retention is lower with the gate at level 40.
- Checking the download, I saw 90,189 rows, 44,700 players in `gate_30` and 45,489 in `gate_40`, and the retention rate of each arm: 1-day 44.8% and 44.2%, 7-day 19.0% and 18.2%.
- I also saw the game-round means (52.5 and 51.3), medians (17 and 16) and maximums (49,854 and 2,640), and the five largest totals.

What limits the room for choice: the tests, the SRM threshold and the shape of the decision rule are EXP-001's, written on 2026-10-30 before this data was opened. The choices made after seeing the data are marked **(set after seeing the data)** below. The readout code that runs this plan was written after the plan was committed.

## Hypothesis

> Because Cookie Cats makes a player stop at a gate (wait, or pay, to keep playing), and the first gate at level 30 interrupts players while the game is still new to them, we believed moving the first gate to level 40 would increase 7-day retention.

The opposite is just as plausible: an early forced break might stop players burning out on the game. The test can tell the two apart; the hypothesis only fixes the direction we hoped for.

## Design

| | |
|---|---|
| Unit of randomization | The player, at install |
| Allocation | 50% `gate_30`, 50% `gate_40` (planned) |
| Control | `gate_30`: the first gate at level 30, the game as it shipped |
| Test | `gate_40`: the first gate at level 40 |
| Population | Every player in the file: intent to treat. Many players never reach level 30, so they never see either gate. That dilutes any effect, but the data has no level reached, so they can't be separated out. |

The columns: `userid`; `version` (the arm); `sum_gamerounds`, rounds played in the first 14 days after install; `retention_1` and `retention_7`, whether the player came back and played 1 day and 7 days after install.

## Metrics

| Role | Metric | Test |
|---|---|---|
| Primary | **7-day retention**: share of players with `retention_7` true | Two-sided z-test for test − control with a 95% Wald interval. A percentile bootstrap of the difference (2,000 resamples of players, seed 0) as a check. |
| Secondary | 1-day retention: share with `retention_1` true | Same as the primary. |
| Secondary | Game rounds in the first 14 days, per player, zeros included | Welch's t-test on the mean. Percentile bootstrap of the difference in medians, because the distribution has a long right tail. |
| Guardrail | Players who never played a round: share with `sum_gamerounds` = 0 **(set after seeing the data)** | Regresses if test − control is above **+1.0 percentage point**. |

The two secondaries are Holm-corrected together.

The guardrail is a sanity check rather than a business one. A player with no rounds never reached either gate, so the arms should match; a gap would mean the `gate_40` build or the assignment broke something before play started. The guardrails a studio would really watch, like revenue, crashes or ad views, aren't in the data.

### Outliers

No player is dropped from the analysis of record. Every game-round total that isn't plausible for one person in 14 days gets investigated and reported. The cap is **10,000 rounds (set after seeing the data)**, about 714 a day, or a round every two minutes around the clock. The secondary is then rerun without those players as a sensitivity check that decides nothing.

### CUPED doesn't apply

CUPED reduces variance with each player's behavior from before the experiment, and every player here was assigned at install, so there's no "before". The other columns are measured after assignment: game rounds and 1-day retention can be changed by the gate, so adjusting for them would bias the estimate rather than sharpen it. A pre-assignment attribute (device, country, install source) would allow regression adjustment like EXP-001's, but the file has none. The readout is unadjusted.

## Sample size check

| Input | Value |
|---|---|
| Baseline 7-day retention | **19.0%**, from the control arm itself **(set after seeing the data)**. There's no earlier data. |
| MDE | **±1.0 percentage point** absolute, about 5% relative **(set after seeing the data)** |
| Alpha | 0.05, two-sided |
| Power | 0.80 |
| **Required** | **24,641 players per arm** |

From `uv run liftlab power --baseline 0.19 --mde 0.01`. The arms have 44,700 and 45,489 players, so the test has 96.5% power for a 1-point change and could detect 0.74 points at 80%. If the gate moves 7-day retention by a point or more, this data should show it.

## Analysis plan

Run in this order by `liftlab cookie-cats`:

1. **Sample ratio mismatch.** A chi-square test of players per arm against 50/50. p < 0.001 means the data can't be trusted to decide anything. This is EXP-001's threshold.
2. **Primary.** 7-day retention by arm, the difference with its 95% CI and p-value, then its bootstrap interval.
3. **Guardrail.** The never-played share by arm, its difference and CI.
4. **Secondaries.** 1-day retention and game rounds, each with its test and bootstrap, then Holm.
5. **Outliers.** List every player over the 10,000-round cap, describe them, and rerun the game-rounds Welch test without them.
6. **Decision rule**, below, applied once.

## Decision rule

Top to bottom; the first rule that matches decides.

1. **INVALID** if the SRM check fails (p < 0.001). No decision.
2. **UNDERPOWERED** if either arm has fewer than 24,641 players. No decision.
3. **KILL**, keep the gate at 30, if the guardrail regresses: never-played share in `gate_40` more than +1.0 point above `gate_30`.
4. **SHIP**, move the gate to 40, if the 95% CI for 7-day retention (test − control) is entirely above 0 and no secondary is significantly worse after Holm.
5. **ITERATE** if the 7-day retention point estimate is at least +0.5 points (half the MDE): a follow-up test before moving the gate.
6. **KILL**, keep the gate at 30, otherwise.

The default is the game as it shipped. Moving the gate needs evidence that it helps; keeping it needs none.
