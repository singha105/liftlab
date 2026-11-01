# LiftLab on a resume and in interviews

Every number here comes from this repo, with the doc it comes from. **REAL** means real people (the public Cookie Cats test). **SYNTHETIC** means the simulator, with known ground truth. StudySprint itself has had no real users yet, so nothing here claims user impact, growth or a lift on real users.

## Resume bullets

Pick the option that fits the role. Each bullet stands on its own.

**Option A: product and growth**

- Shipped StudySprint, a focus timer for students (TypeScript, PostHog, GitHub Pages, 6.2 kB gzipped JS), and defined its North Star (weekly completed sessions), metric tree and a privacy-first tracking plan enforced by tests.
- Pre-registered a Quick Start A/B test behind a PostHog feature flag; power analysis showed it needed 1,377 users per arm, 551 days at real traffic, so I validated the method on simulations and a public test instead of over-reading an underpowered result.
- Analyzed a 90,189-player public A/B test (Cookie Cats) end to end and wrote the decision memo: moving the gate to level 40 cut 7-day retention by 0.82 points (95% CI −1.33 to −0.31), so the call was to keep it at level 30.

**Option B: data science and experimentation**

- Built a Python experiment-analysis library (SRM, z and Welch tests, delta method, bootstrap, CUPED, mSPRT sequential testing, Holm), cross-checked against scipy and statsmodels, with a pre-registered decision rule that outputs SHIP, ITERATE or KILL.
- Simulated 1,000 A/A experiments peeked at daily for 28 days: naive peeking raised false positives to 27.3% while the mSPRT held 1.7%; CUPED cut variance 22% with coverage kept at 95.6%.
- Re-analyzed the 90,189-player Cookie Cats test with SRM checks, z-tests, 2,000-resample bootstrap intervals and an outlier review (one player at 49,854 rounds, kept and reported), and recommended against the change: 7-day retention −0.82 points (p = 0.0016).

**Option C: software and data engineering**

- Built a DuckDB warehouse and 7 SQL models (funnel, D1/D7/D28 retention, North Star, experiment users) fed by a PostHog export and a seeded simulator (20,000 users and 358,000 events in 2.3 s), with SQL tested against the simulator's ground truth: activation averaged the true 30.69% exactly across six seeds.
- Shipped a vanilla-TypeScript web app on GitHub Pages with an analytics layer typed from the tracking plan, feature-flag exposure logic, and 63 tests, including a fix that kept slow or ad-blocked visitors out of the control arm instead of creating a sample-ratio mismatch.
- Wrote 194 Python tests and a two-job GitHub Actions CI (uv, ruff, pytest; npm type-check, tests and build), plus a Streamlit dashboard that runs with no secrets or local data, all at $0.

If there's room for one line: *Built LiftLab, an end-to-end experimentation project: a shipped app with a North Star and tracking plan, DuckDB SQL models, a stats library proven on 1,000-run simulations (peeking 27.3% false positives vs 1.7% with mSPRT), and a keep-at-30 decision on a 90,189-player public A/B test.*

## Interview pitch

I built a small product, a study timer, and everything a growth team would use to improve it: a North Star and metric tree, a privacy-first tracking plan, SQL models, pre-registered A/B tests and a stats library. When the power analysis showed my own test would need 551 days of traffic, I didn't fake a result; I proved the method where the answer was known and used it to make a real call on a 90,189-player public A/B test.

## Likely questions

**1. Why mSPRT over a fixed-horizon test?**
- I use both, for different jobs ([ADR 0004](decisions/0004-fixed-read-sequential-monitoring.md)). The primary is read once at the planned N with a fixed-horizon z-test, because that's what the sample size was computed for.
- Peeking is the problem the mSPRT solves: on 1,000 simulated A/A tests checked daily, stopping at the first p < 0.05 gave 27.3% false wins; the mSPRT gave 1.7% (SYNTHETIC).
- Its guarantee holds for any number of looks, which makes it conservative and costs power. That's the right trade for weekly guardrail checks, where an early stop protects users, and the wrong one for the metric I hope to ship on.
- Each guardrail's mixing sd is its own threshold, and a run stops early only if the always-valid interval lies entirely past it.

**2. What would you do with an underpowered test?**
- Say so before launch. EXP-001 needs 1,377 per arm; at about 5 users a day the 8-week cap gives about 140, where it detects a +5-point lift 14.5% of the time and the smallest reliable lift is 16.2 points.
- Don't act on it either way. The pre-registered rule calls it UNDERPOWERED and the product stays on control: not significant says almost nothing, and significant would most likely overstate the lift.
- Change the inputs, not the bar: more traffic, a longer run, a bigger MDE only if the business would act on nothing smaller, or variance reduction. CUPED needs pre-period data that new users don't have, and regression adjustment on device and referrer removed almost no variance in the simulator.
- Use the run for what it can show: that assignment, exposure and the data pipeline work.

**3. Why weekly completed sessions as the North Star?**
- A completed session is the unit of value; an open tab proves nothing, and focus minutes rewards long sessions over follow-through ([ADR 0001](decisions/0001-north-star.md)).
- It splits exactly into weekly active users × sessions per active user × completion rate, so every experiment names the input it moves.
- It can be gamed with short sessions, so the shortest preset is 15 minutes and the length mix is a health metric. The ADR lists what would make me switch, such as the top 10% of users producing over half the total.

**4. Walk me through Cookie Cats. Was it fair, given the answer was already known?**
- I wrote a retrospective pre-registration that says so at the top, listed what I'd seen, and marked every choice made after seeing the data.
- SRM passed (p = 0.0086 against 0.001), both arms had over the 24,641 players they needed, the guardrail held, and 7-day retention fell 0.82 points with an interval entirely below zero, so KILL: keep the gate at 30 (REAL).
- Only the MDE could have changed the answer: below 0.75 points the read would have been UNDERPOWERED. One player had 49,854 rounds; I kept them in and reported the with/without comparison rather than dropping them.
- Risks I named: the split would fail at 0.01, the data has no revenue or level reached, and it's one test, in a file dated 2019. What I'd test next is the same comparison, instrumented.

**5. How do you know your numbers are right?**
- Every stats function is checked against scipy or statsmodels, and every method on simulations where the truth is known: 5.8% false positives on 1,000 A/A tests, 81.8% power against 79.6% expected (SYNTHETIC).
- When 800 no-effect runs flagged 7.1%, I looked for a bug before writing it down: same result without the warehouse, 5.4% with relabeled arms, then 4.9% on 1,600 fresh seeds. It was an unlucky block, and the lesson was to judge error rates on 1,000+ runs.
- The SQL is tested against ground truth (activation 29.95% against a true 30.69% on one seed, exactly 30.69% on average across six).
- Building the feature flag, I caught a design bug: slow or ad-blocked visitors were defaulting to control, which would have built a sample-ratio mismatch into the test. Now only a loaded flag enrolls anyone.

## Numbers you can quote

| Number | Label | Source |
|---|---|---|
| 90,189 players; 7-day retention 19.02% → 18.20%, −0.82 points [−1.33, −0.31], p = 0.0016 | REAL | [EXP-000 memo](experiments/EXP-000-memo.md) |
| SRM p = 0.0086; 24,641 players per arm needed; outlier at 49,854 rounds | REAL | [EXP-000 memo](experiments/EXP-000-memo.md) |
| StudySprint live users: 0 (no PostHog key yet) | REAL | [EXP-001 interim](experiments/EXP-001-interim.md) |
| 1,377 users per arm; 551 days at 5 a day; 140 per arm at the 8-week cap: 14.5% power, MDE 16.2 points | plan | [EXP-001](experiments/EXP-001.md), [interim](experiments/EXP-001-interim.md) |
| Peeking 27.3% vs mSPRT 1.7%; A/A 5.8%; CUPED −22% variance; power 81.8% | SYNTHETIC | [STATS.md](STATS.md) |
| Funnel: 50.5% of new users never start; activation 30.0% | SYNTHETIC | [ANALYTICS.md](ANALYTICS.md) |
| 194 Python tests, 63 app tests; 6.2 kB gzipped JS | repo | [PROGRESS.md](PROGRESS.md) |
