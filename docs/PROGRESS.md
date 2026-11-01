# Progress

## Day 1, 2026-10-29: strategy docs and scaffold

### Done

- [Product brief](PRODUCT_BRIEF.md): target user, job to be done, core loop, v1 scope in and out.
- [Metrics](METRICS.md): three North Star candidates scored, a Mermaid metric tree, exact definitions for activation, D1/D7/D28 retention, active users and guardrails.
- [ADR 0001](decisions/0001-north-star.md): the North Star is weekly completed sessions.
- [Tracking plan](TRACKING_PLAN.md): seven events with typed properties, session lifecycle, exposure rules and privacy rules.
- [Experiment backlog](EXPERIMENT_BACKLOG.md): five ICE-ranked hypotheses aimed at activation. #1 (Quick Start for new users) is the Day 4 experiment.
- Scaffold: `app/` (create-vite 9.3.3, vanilla-ts template: Vite 8.3.5, TypeScript 7.0), `analysis/` (uv package `liftlab`, Python 3.12, pytest + ruff), `data/` (gitignored apart from `.gitkeep`), `.gitignore`, `.env.example`, MIT license, README.

### Decisions

- **North Star: weekly completed sessions.** It splits exactly into WAU × sessions per active user × completion rate. ADR 0001 lists what would make us switch.
- **Weakest input: activation (assumed ~30%).** Every baseline in the backlog is an assumption until real traffic exists. The Day 3 generator will use the same numbers, so it can't confirm them.
- **Vanilla TypeScript, no UI framework.** The app is a few screens and page load is a guardrail. The Vite demo files were removed and replaced with a placeholder page.
- **Python pinned to 3.12** (`requires-python >= 3.12`), so DuckDB, SciPy and Streamlit wheels are a sure thing later in the week.
- **Privacy is enforced in config.** No autocapture, no session recording, localStorage only, DNT and GPC skip PostHog entirely, and IPs are discarded in the project settings. The `ip: false` init option is deprecated and does nothing, so it isn't relied on.

### Checks

| Check | Result |
|---|---|
| `npm run build` in `app/` | Pass. `tsc` clean; 0.47 kB gzipped JS. |
| `uv run pytest` in `analysis/` | Pass. 1 test. |
| `uv run ruff check` and `ruff format --check` | Pass. |
| Mermaid tree on GitHub | Renders (checked on github.com at desktop width). |
| Ignore rules | `data/raw/*.csv`, `*.duckdb`, `.env`, `node_modules`, `.venv`, `dist` ignored; `data/raw/.gitkeep` and `.env.example` tracked. |

### Open questions

- Custom session lengths are 10 to 90 minutes. Is 10 too short a floor for a North Star that counts sessions? Watch median planned minutes once data exists.
- `elapsed_seconds` on abandon vs `actual_minutes` on completion is deliberate (early abandons are sub-minute), but the units differ. Revisit if it confuses the SQL on Day 3.

### Next: Day 2

- Build StudySprint v1 to the brief: timer with pause and resume, goal, completion, streak, weekly summary.
- Typed `track()` wrapper generated from the tracking plan, plus tests for the privacy rules.
- PostHog init with the privacy config, then deploy to GitHub Pages with Actions.
- Needs from Arnab: the PostHog `phc_` project key and host, "Discard client IP data" turned on in the PostHog project, and an OK to switch GitHub Pages to the Actions source.

## Day 2, 2026-10-30: StudySprint v1, analytics wrapper, Pages deploy

Live: **https://singha105.github.io/liftlab/** (demo mode: [?demo=1](https://singha105.github.io/liftlab/?demo=1), every minute lasts a second).

### Done

- **StudySprint v1** in `app/`, vanilla TypeScript with no framework. 15, 25 or 50 minute sprints, optional goal chips, pause, resume and give up, a completion screen with the streak, and a weekly summary that compares this week with last week. The timer counts from timestamps, so a background tab or a sleeping laptop doesn't drift, and a reload resumes the running sprint. All state lives in localStorage behind try/catch, with an in-memory fallback when storage is blocked.
- **Away check.** If a sprint ran out while the page was closed, the next visit asks "Did you finish?" A yes counts it with `completed_while_away: true`; a no records `session_abandoned` with reason `page_closed`. A sprint paused for over a day, or left unanswered for over a day, is abandoned as `stale`.
- **Accessibility.** Keyboard-only use works throughout: radio-group lengths, `aria-pressed` chips, native `<dialog>` for confirmations, a visible focus ring and 44 px targets. Light and dark themes both pass contrast, reduced motion is respected, and it fits a 375 px screen without sideways scroll.
- **`app/src/analytics.ts`.** The tracking plan is the `PLAN` object; event and property types come from it, so a misspelled property or a 30-minute session fails `tsc`. There's one function per event (`trackSessionCompleted` and so on), plus `getVariant(flag)`, which falls back to `control` when there's no key, PostHog is blocked, or flags take longer than 1.5 s.
- **Privacy in code.** No key, DNT, GPC, or a past opt-out means posthog-js is never downloaded. When it is loaded, autocapture, pageviews, page leave, heatmaps, exceptions, surveys and recording are all off, and `before_send` drops anything not in the plan. It also strips query strings from every URL property, deletes `$timezone`, `$timezone_offset`, `$set` and `$set_once`, and the footer has a sticky "Turn off analytics" switch.
- **Deploy.** `.github/workflows/deploy-app.yml` runs on pushes to `main` that touch `app/**`, the tracking plan or the workflow. It runs `npm ci`, the tests and the build, with `VITE_POSTHOG_KEY` and `VITE_POSTHOG_HOST` read from repository variables and the commit SHA as `app_version`, then publishes with the official Pages actions. Pages is set to the Actions source.
- Privacy notes in the app footer and the README.

### Tracking plan v2

[TRACKING_PLAN.md](TRACKING_PLAN.md) moved to v2, and the product brief, METRICS, ADR 0001 and the backlog were updated to match.

- Custom lengths were dropped, so `planned_minutes` is `enum(15, 25, 50)` and `start_method` loses `custom`. ADR 0001's farming guard now watches the share of 15-minute sessions (amendment dated today).
- New super property `is_demo`. METRICS drops demo traffic from every metric. `variant` is an enum.
- New `completed_while_away` on `session_completed`. `page_closed` now means "said no in the away check".
- The goal is picked from chips, so backlog #5 (chips instead of a text box) is retired. A new #5, "show how close you are before giving up", takes its place, and #2 now tests the 15-minute preset instead of 10.
- Privacy rule 6 now covers every URL property, the timezone fields and person properties. Rule 7 is the sticky opt-out.

### Decisions

- **PostHog loads after first paint.** posthog-js is a dynamic import and events queue until it arrives, then go out with their original timestamps. The app's own JS is 5.6 kB gzipped without a key and 6.8 kB with one; PostHog is a separate ~104 kB chunk that doesn't hold up `load_ms`.
- **Full posthog-js, not the slim module.** Slim saves about 20 kB, but feature flags on Day 4 depend on parts it leaves out, and saving 20 kB isn't worth risking the experiment.
- **Our own opt-out key.** posthog-js's `opt_out_capturing` still calls `/flags` on the next load, so opting out also stops the library from loading at all.
- **Timezone dropped.** It's coarse location and no metric uses it. Metric time is UTC anyway.
- **No `$feature_flag_called`.** `getVariant` reads flags with `send_event: false`. `experiment_exposed` is the one exposure event, fired where the arms differ.

### Checks

| Check | Result |
|---|---|
| `npm test` | Pass, 47 tests. They cover plan and super-property parity with TRACKING_PLAN.md, `@ts-expect-error` checks for unplanned properties, no `identify`/`alias` anywhere, init config, DNT/GPC/no-key/opt-out never loading PostHog, the event queue, `before_send` drops and stripping, `getVariant` fallbacks, plus the streak, week, session and state logic. |
| `npm run build` | Pass. `tsc` strict with `noUncheckedIndexedAccess`; 1.9 kB HTML, 2.0 kB CSS, 5.6 kB JS gzipped (no key). |
| Deploy workflow | Green: [run 41005827977](https://github.com/singha105/liftlab/actions/runs/41005827977), build and deploy in 36 s. |
| Live site at 375 px | A `?demo=1` 15-minute sprint on the live URL went setup → timer → completion screen ("1 day in a row"). Demo storage logged it; the real `studysprint` key stayed empty. No third-party requests, because no key is set. |
| Local end to end with a key | Built with a test key against a mock PostHog server. Only planned events arrived, each with the right typed properties: `app_opened`, `session_started`, `session_completed`, `session_abandoned`, `streak_viewed`, `weekly_summary_viewed`. No `$pageview`, `$autocapture`, `$feature_flag_called`, `$timezone` or `$set`. Opting out and reloading sent zero requests. |
| Bugs the end-to-end run caught | 1) The away dialog's sprint was being auto-completed by the tab-focus tick, so it arrived with `completed_while_away: false`; the tick now skips when the timer screen is hidden. 2) `$timezone` was being sent; now dropped. Both have tests. |
| Manual | Keyboard-only run, dark mode, reduced motion, give-up and away dialogs, streak and summary dialogs. |

### Open

- **No PostHog key yet**, so the live build sends nothing ("Analytics aren't set up in this build"). The real PostHog Activity check waits on the `phc_` key being added as the `VITE_POSTHOG_KEY` repository variable and the workflow re-running. `VITE_POSTHOG_HOST` is set to US Cloud.
- "Discard client IP data" still needs turning on in the PostHog project settings.
- `experiment_exposed` exists in code but nothing fires it until Day 4 adds the Quick Start flag.

### Next: Day 3

- Synthetic event generator that follows the tracking plan exactly, using the backlog's assumed baselines.
- DuckDB warehouse and the METRICS.md definitions as SQL: activation, D1/D7/D28, WCS and its three factors, guardrails.
- Needs from Arnab: the PostHog key (above), and a Personal API key with read access in `.env` if we pull real events.

## Day 3, 2026-10-30: simulator, warehouse and SQL models

Every number in this entry is **synthetic**: simulated users with known ground truth, not real usage.

### Done

- **Simulator** (`analysis/src/liftlab/simulate.py`).
  - Each user gets a latent motivation that drives starting, finishing, retrying, daily visits, extra sprints and churn.
  - Events follow the tracking plan exactly and look like a PostHog export, including 0.3% duplicate deliveries and 0.4% demo users for the warehouse to remove.
  - It returns a `GroundTruth` computed from the model itself: the start rate, activation rate, D1–D28 curve and expected North Star per week. It also returns a per-user table.
  - Same seed, same output. 20,000 users and 358,000 events take 2.3 s, against a 30 s limit.
- **Experiment mode.**
  - Users are split 50/50 and exposed at their first visit after the start.
  - The activation effect is solved for so the true effect is exactly the number configured.
  - The sessions effect is exact for returning users.
  - `pre_sessions`, the sessions started in the 28 days before exposure, is the CUPED covariate.
  - `srm_loss` drops test exposures to produce a sample-ratio mismatch, and new test users' first sprints use `quick_start`.
- **Warehouse.** `uv run liftlab load --source synthetic|posthog|csv` loads `raw_events` into `data/warehouse.duckdb`. Rows are tagged by source, and loading a source replaces only that source. `warehouse_meta` records where each source's data ends, and `sim_truth` keeps the ground truth.
- **Six SQL models** in `analysis/sql/`, built in order by `liftlab build` in about 1 s: `stg_events`, `fct_sessions`, `dim_users`, `funnel_activation`, `retention_cohorts` and `north_star_weekly`. The last one has the North Star and every input in the metric tree, plus the identity check. Every model keeps `source`.
- **PostHog export.**
  - `uv run liftlab export-posthog` uses the documented query API (`POST /api/projects/:id/query/`, HogQL).
  - It pages by timestamp, because OFFSET is rejected for personal keys, and removes duplicates by `uuid` where pages meet.
  - The key is read from `.env` only and never printed.
  - It's tested against a fake server, **but hasn't run against PostHog**: there's no personal API key or project ID yet, so the command exits with a "not set in .env" message.
- `docs/ANALYTICS.md`: how to run it, a Mermaid diagram of the models, the simulator and its ground truth, and three example questions with their SQL and results.

### Funnel and retention (synthetic, seed 7, 20,000 users)

| step | users | step conversion | overall | drop-off |
|---|---|---|---|---|
| app_opened | 16,881 | 100.0% | 100.0% | 0 |
| session_started | 8,362 | 49.5% | 49.5% | 8,519 |
| session_completed | 5,069 | 60.6% | 30.0% | 3,293 |
| second_session_7d | 4,750 | 93.7% | 28.1% | 319 |

**The biggest drop-off is the first step.** 8,519 of 16,881 new users (50.5%) never start a sprint in their first 24 hours. The next biggest is starters who don't finish: 3,293, or 39% of those who start. Both are assumptions built into the simulator rather than findings, but they make the case for Quick Start (backlog #1), which targets exactly that first step.

| cohort week | users | D1 | D7 | D28 |
|---|---|---|---|---|
| 2026-08-31 | 1,949 | 24.3% | 16.1% | 8.5% |
| 2026-09-07 | 2,134 | 26.0% | 15.1% | 8.2% |
| 2026-09-14 | 2,295 | 25.2% | 14.6% | 8.2% |
| 2026-09-21 | 2,450 | 24.4% | 13.8% | 8.2% |
| 2026-09-28 | 2,448 | 24.6% | 15.2% | – |
| 2026-10-05 | 2,704 | 24.3% | 16.3% | – |
| 2026-10-12 | 2,901 | 25.6% | 13.8% | – |
| 2026-10-19 | 3,056 | – | – | – |

A dash means the period hasn't ended for every member of the cohort yet.

### Checks

| Check | Result |
|---|---|
| `uv run pytest` | Pass, 38 tests in about 10 s. They cover determinism, speed, events matching TRACKING_PLAN.md exactly (property names, types and enum values), and experiment effects, SRM and the covariate. Also SQL against ground truth, the edge cases, the PostHog export and the CLI. |
| SQL vs ground truth | Activation 29.95% against a true 30.69% (−2.2 SE, inside the 1-point threshold). D1 −0.5 SE, D7 14.93% against 15.15% (−0.8 SE), D28 −1.3 SE. Weekly North Star between −0.3 and −3.1 SE, all inside 4 SE. |
| Is the gap a bias? | No. Seed 7 drew a slightly low sample, and all its gaps point the same way because it's the same users every week. Across seeds 1–6, SQL activation averages 30.69%, the truth exactly, and weekly completions average within 1%. Activation also matches the simulator user by user. |
| Edge cases | A user with no sessions; duplicate events, both same-uuid and a resend with a new uuid; a session crossing Sunday midnight; the 24-hour activation boundary to the second; no-end sessions, both stale and still open; demo and unplanned events; incomplete weeks and cohorts. |
| `ruff check`, `ruff format --check` | Clean. |
| Full run from the CLI | load 3.8 s, build 1.3 s, report prints labelled tables. The warehouse is 96 MB and gitignored. |
| Analysis CI | `.github/workflows/analysis.yml` runs `uv sync --locked`, ruff and pytest on every push and pull request, with uv pinned to the version that wrote `uv.lock`. Green: [run 41068192929](https://github.com/singha105/liftlab/actions/runs/41068192929), 38 tests in 22 s, 32 s in all. |

### Definitions pinned down in METRICS.md

The SQL needed a few definitions the doc didn't have yet. None of them changes an existing metric:

- **Activation funnel.** A new section: the four steps, defined on new users with 7 full days of data so that every step is measured on the same people.
- **Weekly retention cohorts.** A weekly cohort's Dn is reported once its last member's day n has ended, which is 7 + n days after the week starts.
- **The metric-tree identity.** It's exact when completions are counted by the week the session started. The North Star counts them by the week they happen, so the two differ by sessions that run across Sunday midnight UTC. `north_star_weekly` shows both, and they're within 1% of each other in every week.
- **Concentration** is now the top 10% of the week's *active* users.
- **New ground rules.** Duplicates by event `uuid` count once, and `csv` is a third source.

The tracking plan didn't change.

### Decisions

- **Truth comes from the model, not the sample.** It's the population value, so the tests allow for sampling error (four standard errors, or the 1-point threshold for activation and D7) rather than expecting an exact match. This is also what Day 5 needs to check whether confidence intervals cover the true effect.
- **First-day timing is designed so activation is exact.** Every first-day sprint ends within 22.3 hours of arrival, and later visits start at least 24 hours after it, so timing can't blur activation. D1 still includes first-day sprints that start after UTC midnight, and the truth integrates that in closed form.
- **The weekly North Star truth counts sessions by the day they started.** The SQL counts completions when they happen. The difference is the Sunday-midnight sessions above, far inside the tolerance.
- **The query API, not batch exports, for PostHog.** PostHog says `/query` isn't meant for large exports. StudySprint's real volume is tiny, though, so paging the query API is fine and costs nothing. If it ever passes 50,000 events a day, switch to a batch export.
- **Dependencies:** duckdb 2.0, numpy 2.5 and pandas 3.1. No SciPy needed yet: the quadrature comes from NumPy.

### Worth knowing

- **The backlog's baselines are aggressive taken together.** A 15% D7 with 30% activation means 46% of activated users come back on day 7 exactly (query 3 in ANALYTICS.md), and 94% start another session within a week. Real students are unlikely to be that loyal. When real data exists, re-check the D7 assumption first, since it also sets the Day 4 sample size.
- Sprints with a goal finish 8 to 11 points more often at every length. In the simulator a quarter to a third of that is selection, because motivated users pick goals more. Real data would have the same confounding.

### Open

- **PostHog keys.** The front-end `VITE_POSTHOG_KEY` is still unset (Day 2), so the live app sends nothing. The export also needs `POSTHOG_PROJECT_ID` and a `POSTHOG_PERSONAL_API_KEY` with the query:read scope in `.env`.
- The Day 2 check of events in PostHog's Activity view is still pending, for the same reason.

### Next: Day 4

- Pre-register the Quick Start experiment, sizing it from the 30% activation baseline.
- Add the PostHog feature flag and the app change, firing `experiment_exposed` only where the arms differ.
- Do a simulated readout with `Experiment(audience="new")`.

## Day 4, 2026-10-30: EXP-001 pre-registered, power module, Quick Start behind a flag

Numbers marked synthetic come from the simulator, not from real users.

### Done

- **Power module** (`analysis/src/liftlab/stats/power.py`).
  - Sample size per arm, power and the inverse (the MDE a given N can detect), for two proportions and for a difference in means.
  - Absolute or relative MDE, two-sided by default, plus the duration in days at a given number of eligible users a day.
  - Standard library only. The tests check it against statsmodels, which is a dev-only dependency: sample sizes are the smallest N statsmodels says is enough, and power agrees to 1e-12. `uv run liftlab power` prints a plan.
- **Pre-registration**, [docs/experiments/EXP-001.md](experiments/EXP-001.md). It covers:
  - the hypothesis from backlog #1, randomized by anonymous `distinct_id`, 50/50, new users only, with an exact exposure rule;
  - activation as the primary metric, completed sessions per user in 7 days as the secondary, and abandon rate (+2.0 points) and page-load p75 (+10%, or above 2,000 ms) as guardrails;
  - sample size, duration and feasibility;
  - the analysis order (SRM, primary, guardrails, secondary, CUPED, sequential monitoring);
  - a six-step decision rule.
- **Quick Start variant behind `exp-001`.**
  - On a device's first open, the app reads the flag. If it loads within 1.5 s with `control` or `test`, and the start screen is still untouched, `experiment_exposed` fires once and the arm is saved and registered as super properties.
  - The test arm switches to one "Start a 25-minute focus" button (`start_method: quick_start`, no goal), with the usual choices behind "Customize length or goal". It keeps that screen until the first session starts.
  - In control, nothing visible changes.
  - Demo mode is never enrolled; `?demo=1&variant=test` previews the test arm.
- **A bug fix in `getVariant`.** Before, a slow or blocked flag returned `control`. Exposing those users would have put every ad-blocker and slow-network visitor into the control arm only, which is a built-in sample-ratio mismatch. Now it returns `null` (no arm, see control, never exposed). The tracking plan is v3 with the exposure rules; no events or properties changed.
- **PostHog setup steps**, [docs/experiments/EXP-001-posthog-setup.md](experiments/EXP-001-posthog-setup.md), for doing it by hand: the flag, the custom exposure event with filters, a funnel primary metric with a 24-hour window, the secondary and abandon-rate metrics, frequentist statistics, and launch checks.
- **Dry run** (`uv run liftlab dry-run`). It simulates `exp-001` experiments with a known effect, runs each one through the warehouse and SQL models, stops at N per arm the way the real read will, and applies the pre-registered z-test. The simulator's experiment key is now `exp-001`, the real flag key.

### Pre-registered before the variant

```
81f2df5 docs: pre-register EXP-001 Quick Start experiment
628f23e test(app): snapshot the start screen before EXP-001
28fb30d feat(app): add Quick Start variant behind the exp-001 flag
```

The pre-registration was pushed on its own before any variant code existed, so GitHub has its timestamp. The start-screen snapshot was recorded from the app as it was then, and the variant commit doesn't touch it.

### The plan

Baseline activation 30.0% (synthetic, from Day 3's funnel: 5,069 of 16,881 new users) | MDE +5.0 points absolute (+16.7% relative) | alpha 0.05, two-sided | power 0.80

**Required: 1,377 users per arm, 2,754 in total.**

| Eligible new users a day | Days |
|---|---|
| 5 (realistic for StudySprint) | 551 |
| 10 | 276 |
| 40 | 69 |
| 100 | 28 |

StudySprint can't reach that. The live run is capped at 8 weeks, which at 5 users a day is about 140 per arm, enough to detect only a 16-point lift. It's there to prove the flag, exposure and tracking pipeline; the statistics are validated on the simulator here and on the Cookie Cats data on Day 6. EXP-001.md says so up front, in its feasibility section.

### Dry run (synthetic)

Each run simulates new users arriving into a 50/50 `exp-001` test over two weeks, builds the warehouse, reads exposed users in exposure order until both arms have 1,377, and applies the pre-registered two-sided z-test at alpha 0.05.

| Runs | True effect | Detected | Expected |
|---|---|---|---|
| 200 at the MDE (seeds 1-200) | +5.0 points | **157, empirical power 78.5%** (95% CI 72.3% to 83.6%) | 79.6% |
| 800 with no effect (seeds 1001-1800) | 0 | 57, false-positive rate 7.1% (5.5% to 9.1%) | 5.0% |
| 1,600 with no effect (seeds 2001-3600) | 0 | 78, false-positive rate 4.9% (3.9% to 6.0%) | 5.0% |
| All 2,400 with no effect | 0 | 135, false-positive rate 5.6% (4.8% to 6.6%) | 5.0% |

- Expected power is 79.6%, not 80%, because the simulator's true control rate is 30.7% and the plan used 30.0%. A higher base rate has a little more variance.
- At the MDE the mean estimated lift was +5.07 points against a true +5.0, and no run detected an effect in the wrong direction. Mean arm sizes were 1,399 and 1,400; the read stops when the smaller arm reaches 1,377, so the other one runs slightly over.
- Run 1 (seed 1), as an example: control 419 of 1,377 = 30.4%, test 520 of 1,387 = 37.5%, a difference of +7.1 points (95% CI +3.5 to +10.6), z 3.92, p 0.0001.
- The no-effect runs started badly. The first 200 flagged 17 (8.5%), and 800 flagged 57 (7.1%), which has about a 0.5% chance at a true 5% rate. So I looked for a bug before writing it down:
  - The same seeds read straight from the simulator's ground truth, skipping the warehouse, give the same result: 57 detections, with the same z mean (0.00) and standard deviation (1.05). The SQL isn't the cause.
  - With no effect, nothing in the simulator depends on the arm: the start shift is exactly 0, and the only difference is the `start_method` label.
  - On those 800 seeds, randomly relabelling the arms gave 5.4%, and replacing the outcomes with coin flips gave 4.9%.
  - 1,600 fresh seeds then gave 4.9%.

  Seeds 1001-1800 were an unlucky block, and the test holds its 5% level. It's also why one 200-run check isn't enough to judge a false-positive rate.

### Checks

| Check | Result |
|---|---|
| `uv run pytest` | Pass, 80 tests (38 before). New: power, sample size and MDE against statsmodels for proportions and means, one- and two-sided, absolute and relative; the EXP-001 plan (1,377 per arm); duration rounding and input errors; the dry run's z-test and Wilson interval against statsmodels; a small dry run read through the warehouse; the `power` and `dry-run` commands. |
| `ruff check`, `ruff format --check` | Clean. |
| `npm test` | Pass, 63 tests (47 before). New: control matches the pre-experiment snapshot with no flag and with a `control` flag; the test arm switches at exposure and exposes once; no exposure if the screen was touched first, for returning visitors, or in demo mode; Quick Start sends `quick_start`, 25 min, no goal; Customize opens the normal screen; Quick Start persists until the first session; `getVariant` gives no arm for slow, missing or unknown flags; saved arms survive reloads and bad data. |
| Control, byte for byte | The snapshot test passes in jsdom. In a real browser with a `control` flag from a mock PostHog, the rendered `<main>` is identical to the snapshot, all 3,120 characters. |
| End to end against a mock PostHog | **Test flag:** Quick Start shows; `experiment_exposed` arrives once with `experiment_key: exp-001`, `variant: test` and `$feature/exp-001: test`; the Quick Start click sends `session_started` with `start_method: quick_start`, 25 min, `goal_set: false`, `session_number: 1`. **Control flag:** one exposure with `variant: control`, screen unchanged. **Flag 3 s late:** control screen, no exposure, nothing saved. No `$feature_flag_called` in any run. |
| Deploy | Green: [run 41162632400](https://github.com/singha105/liftlab/actions/runs/41162632400). The live site has no PostHog key yet, so everyone sees control and nothing is sent; the demo preview shows the deployed Quick Start screen. |
| Bundle | 16.6 kB JavaScript (6.2 kB gzipped), up from 14.9 kB (5.6 kB). |

### Decisions

- **Only a loaded flag enrolls anyone.** See the `getVariant` fix above. Users without a flag are absent from the analysis rather than counted as control.
- **Exposure is checked before the arm is known.** First open, flag in time, screen untouched: each condition applies to both arms equally, so it filters them the same way. The cost is that a test user sees the normal screen for up to 1.5 s before Quick Start replaces it. Holding the screen back until the flag loads would have changed the control experience.
- **+5 points as the MDE.** It's about the lift the backlog's impact score assumed. +3 points would need 3,763 per arm. A true lift of 2 or 3 points will most likely end as ITERATE.
- **The secondary counts completed sessions, not started ones.** Quick Start raises starts by design; completed sessions are the North Star counted per user.
- **Guardrails are judged on the point estimate.** With about 2 ended sessions per user in the first week, the abandon-rate difference has a standard error of about 1.4 points (delta method, synthetic), so a +2.0-point threshold will raise a false alarm about 8% of the time when nothing has changed. That's accepted, because more abandoned sessions is this test's main risk.
- **CUPED doesn't apply to EXP-001.** New users have no pre-experiment behavior to adjust with. Day 5 validates CUPED on the simulator's returning-user experiments; EXP-001 gets a regression-adjusted sensitivity check on device type and referrer only.
- **No PostHog release conditions.** StudySprint never creates person profiles, so there's nothing to target "new users" on. The app enforces it by reading the flag only on a first open.
- **The simulator's Quick Start sprints keep the usual length mix**, while the app's are always 25 minutes with no goal. The activation effect is set directly, so the dry run's ground truth doesn't depend on it.

### Open

- **PostHog by hand** (EXP-001-posthog-setup.md): the `phc_` key as the `VITE_POSTHOG_KEY` repository variable plus a deploy rerun, "Discard client IP data", then create and launch the experiment. Record the launch date here; the 8-week limit runs from it.
- The personal API key and project ID in `.env` for `liftlab export-posthog`, which is needed to analyze the live run.

### Next: Day 5

The stats library:
- an SRM check;
- the z-test and Welch test with confidence intervals;
- the delta method for ratio guardrails like abandon rate;
- a bootstrap for the p75 load time;
- CUPED, validated on the simulator's returning-user experiments;
- a sequential test for the weekly guardrail checks.

Then a full simulated EXP-001 readout through the pre-registered decision rule.

## Day 5, 2026-10-31: stats library, readout, weekly checks, simulation proofs

Every number in this entry is **synthetic**: simulated users with known ground truth, not real usage.

### Done

- **The stats library** (`analysis/src/liftlab/stats/`), one module per job:
  - `srm.py`: chi-square sample ratio mismatch check, flagging at p < 0.001.
  - `tests.py`: the two-proportion z-test, Welch's t-test and the delta method for ratio metrics, each with an absolute and a relative lift and 95% intervals. Day 4's dry run now uses this z-test.
  - `bootstrap.py`: a vectorized, seedable percentile bootstrap that resamples users, not values.
  - `cuped.py`: CUPED and regression adjustment, with the variance reduction.
  - `sequential.py`: the mSPRT from Johari, Pekelis and Walsh, with always-valid p-values and confidence sequences, and the mixing parameter from their equation 12.
  - `multiple.py`: Holm's step-down correction.
- **`experiment_users`**, the seventh SQL model: one row per exposed user with what the readout needs, from the arm and first exposure to 7-day sessions, the 28-day pre-period and page loads after exposure.
- **`liftlab readout`** runs EXP-001's plan from [EXP-001.yaml](experiments/EXP-001.yaml): SRM, then the primary with and without its adjustment, the guardrails, the secondaries with Holm, and the decision rule. It prints SHIP, ITERATE or KILL (or INVALID or UNDERPOWERED) with the reason for every rule it checked, as Markdown or JSON.
- **`liftlab monitor`** runs the weekly checks from step 6 of the analysis plan: SRM on everyone exposed so far, and an mSPRT confidence sequence for each guardrail.
- **Amendment 1 to EXP-001**, dated today and before launch. Step 6 said the weekly guardrail checks would use the sequential test without saying how. The amendment says how: a look every 7 days, guardrails on users whose 7-day window has closed, each guardrail's threshold as its mixing sd, and an early stop only if a guardrail's always-valid interval lies entirely past its threshold. The primary metric, the read and the decision rule are unchanged.
- **`liftlab proofs`**: five simulation proofs, run through the simulator and the warehouse, with charts in `docs/img/` (light and dark) and the numbers in `docs/img/stats-proofs.json`.
- **[docs/STATS.md](STATS.md)**: every method in two plain sentences, when to use it, its formula, what checks it, and its simulation result.

### Simulation proofs (synthetic)

**A/A false-positive rate: 5.8% | Peeking daily, naive: 27.3% vs mSPRT: 1.7% | CUPED variance reduction: 22%**

From `uv run liftlab proofs`, which took 58 minutes on 8 cores. The charts and what each method is are in [STATS.md](STATS.md); the numbers are in [img/stats-proofs.json](img/stats-proofs.json).

| Proof | Result | Should be |
|---|---|---|
| A/A: 1,000 experiments with no effect, read once at 1,377 per arm (seeds 10,001 on) | 58 significant: **5.8%** (95% CI 4.5% to 7.4%). p-values close to flat, 37 to 65 per bin against 50. | 5% |
| Peeking: 1,000 A/A experiments of new users, a look a day for 28 days, about 1,366 per arm by the last | Fixed-horizon z-test, stopping at the first p < 0.05: **27.3%** (24.6% to 30.1%). mSPRT: **1.7%** (1.1% to 2.7%), none in the first week. The z-test read once, at the last look: 4.9%. | mSPRT at most 5% |
| CUPED: 1,000 A/A experiments on all users, about 2,380 each, 28-day pre-period | Variance **−22%** across experiments (−21% as each readout reported), intervals 11% narrower, coverage 95.6% (95.3% unadjusted). Returning users alone: −8%. | coverage 95% |
| SRM: 300 experiments per size and split | 52/48 flagged in **16%** at 2,743 users, 75% at 9,960, 99% at 19,920. 50/50: 0 of 300 at each size. | 12%, 76%, 99% (theory); 0.1% |
| Power: 1,000 experiments with a true +5.0 points, 1,377 per arm | 818 detected: **81.8%** (79.3% to 84.1%). Mean estimate +5.14 points. | 79.6% |

### Example readout (synthetic)

One simulated EXP-001 (seed 4, 3,581 users over two weeks, a true activation effect of +5.0 points), read with `liftlab readout`:

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

The estimate came out at +9.9 points against a true +5.0, and its interval misses the truth. That's one draw. Over 40 seeds of the same setup the readout's mean estimate was +5.12 points (standard error 0.33) and 36 of 40 intervals covered +5.0, so the readout path isn't biased.

### Checks

| Check | Result |
|---|---|
| `uv run pytest` | Pass, 167 tests (80 before) in 42 s. New: SRM against a textbook value and scipy; the z-test against statsmodels, with A/A size and coverage; Welch against scipy; the delta method by hand, against Welch, and its coverage on clustered sessions; Holm against statsmodels and its family-wise error; the bootstrap against scipy, its coverage and its user-level resampling; CUPED against statsmodels OLS, with its bias, coverage and variance reduction; the mSPRT by hand, against numerical integration, under continuous monitoring, and the |z| ≥ 3.04 it needs to reject; every branch of the decision rule; `experiment_users` against the simulator's truth; the weekly checks (stops for SRM, a large regression and both page-load limits, not for one just past the threshold, and the bounds equal the mSPRT of each week's estimate); and each proof at a few runs, with its charts. |
| `ruff check`, `ruff format --check` | Clean. |
| Proofs reproduce | A second run of the peeking and power proofs (after a chart label fix) gave exactly the same numbers: the seeds are fixed. |
| Charts | All ten PNGs looked at in both themes. The palette passes the dataviz validator's checks in light and dark. |

### Decisions

- **CUPED's θ is pooled within arms.** That makes the estimate exactly the arm coefficient of the regression y ~ arm + x, which statsmodels can check, and lets the same code do regression adjustment with several covariates.
- **The mSPRT's mixing sd for EXP-001's primary is 0.0620**, from equation 12 with τ = the 5-point MDE and M = the planned 1,377 per arm. For the guardrails it's their threshold (Amendment 1).
- **Weekly guardrail checks stop only on an always-valid interval past the threshold.** Using the point estimate every week would mean about 8 chances to cross +2.0 points by luck, against the one chance the read gets. At the read, the point estimate still decides, as pre-registered.
- **The bootstrap resamples users, each with all their page loads.** Users were randomized, and one user's loads move together.
- **Holm runs even with one secondary**, where it changes nothing, so a second secondary can't be added without it.
- **The relative-lift interval uses the delta method**, not Fieller's. Every control here is far from zero, where the two agree.
- **The A/A and power proofs reuse Day 4's dry run**, which reads activation from `dim_users`. The peeking, CUPED and SRM proofs read `experiment_users`. The 40-seed check above covers the readout's own path.

### Worth knowing

- **EXP-001's SRM check is weak at its own N.** At 2,754 users it catches a 52/48 split only about 12% of the time; catching it 80% of the time takes about 10,700 users. At EXP-001's N it's reliable only for about 54/46 or worse, and in the live run (about 140 users per arm) for about 62/38 or worse. The proof agrees with the theory at 10,000 and 20,000 users; its 16% at 2,743 is 2.2 standard errors high, most likely chance.
- **CUPED's gain on the simulator is modest**: 22% for all users and 8% for returning users alone, which matches the correlations (about 0.46 and 0.29). A returning user's last month predicts their next week only weakly in the simulator, and part of the 22% is just the covariate telling new users from returning ones. Real data with more history usually does better, but that's not shown here.
- **EXP-001's regression adjustment on device type and referrer removes almost no variance** in the simulator, because the simulator doesn't make activation depend on either. On real users it might.
- **The weekly guardrail checks can only stop large regressions.** Six simulated weeks of EXP-001 left the abandon-rate interval at about ±3.5 points, so an early stop needs a true regression of about +5.5 points or more. Smaller ones wait for the read, as the amendment intends.
- **mSPRT is conservative with daily looks**: 1.7% against a 5% bound, because the bound holds for any number of looks. The price is power. It's used for monitoring, never for EXP-001's primary.

### Open

- **PostHog by hand**, still: the `phc_` key as the `VITE_POSTHOG_KEY` repository variable plus a deploy rerun, "Discard client IP data", then create and launch the experiment. Set `launch:` in EXP-001.yaml on launch day.
- The personal API key and project ID in `.env` for `liftlab export-posthog`.
- The Cookie Cats CSV for Day 6.

### Next: Day 6

Re-analyze the public Cookie Cats A/B test (about 90,000 players) with the same library: SRM, 1-day and 7-day retention with z-tests and bootstrap intervals, and a readout with a decision. It's the library's first real data.

## Day 6, 2026-10-31: Cookie Cats re-analysis, EXP-001 interim read, dashboard

**Cookie Cats decision (REAL): keep the first gate at level 30, because moving it to level 40 lowered 7-day retention from 19.02% to 18.20% (Δ −0.82pp, 95% CI [−1.33, −0.31]) with the SRM check passed (p = 0.0086).**

Labels in this entry: every Cookie Cats number is **REAL** (the public Kaggle test, 90,189 players). EXP-001's live read is **REAL** with N = 0. EXP-001's full-size readout and every StudySprint page in the dashboard are **SYNTHETIC**: simulated users with known ground truth, not real usage.

### Done

- **[EXP-000](experiments/EXP-000-cookie-cats.md), a retrospective pre-registration** of the Cookie Cats test, written after the data existed and saying so at the top. It lists what I'd seen before writing it and marks each choice made after seeing the data: the MDE, the guardrail, the 10,000-round outlier cap and the baseline. It was committed (3cd6842) before any of the readout code.
- **The readout library, extended for real data.** Every readout carries a label, SYNTHETIC or "REAL: <source>, N = x", with ", underpowered (needs n per arm)" when it is. Each metric can have bootstrap intervals for the mean or the median, guardrails can be proportions, and each decision maps to what it means for the product ("KILL: keep the gate at level 30").
- **`liftlab cookie-cats`** loads the Kaggle CSV, checks its columns and duplicates, runs EXP-000's plan, reports every player over the cap, and draws the charts.
- **[EXP-000 readout](experiments/EXP-000-readout.md) and [decision memo](experiments/EXP-000-memo.md)**: recommendation, evidence, the outlier, why there's no CUPED, risks, and what to test next.
- **Amendment 2 to EXP-001**, dated today and before launch: interim reads are descriptive. Rule 2 makes any read before 1,377 per arm UNDERPOWERED, so no interim number can ship or kill Quick Start. The primary metric, the read and the decision rule are unchanged.
- **`liftlab readout --interim`** and **[EXP-001-interim.md](experiments/EXP-001-interim.md)**: the REAL read (N = 0) and the SYNTHETIC full-size run, kept apart.
- **The metric tree as an image**, drawn from the Mermaid block in METRICS.md by `liftlab metric-tree`, so the doc stays the source.
- **The Streamlit dashboard** (`analysis/dashboard.py`): Overview, Funnel (biggest drop-off in orange), Retention (D1/D7/D28 heatmap), Experiments (EXP-000, EXP-001's REAL and SYNTHETIC tabs, or any uploaded CSV, plus the sample-size calculator) and Stats proofs. Every page has a REAL or SYNTHETIC badge. Screenshots are in `docs/img/dashboard-*.png`.
- **Community Cloud prep.** No secrets. The dependency file is `analysis/uv.lock` (Streamlit added as a uv dependency group), and the theme moved to `.streamlit/config.toml` at the repo root, the only place Community Cloud reads it. Deploy steps are in the README. Not deployed.

### Cookie Cats (REAL)

From `uv run liftlab cookie-cats`. Players were randomized at install to `gate_30` (44,700) or `gate_40` (45,489).

| Metric | gate_30 | gate_40 | gate_40 − gate_30 (95% CI) | p |
|---|---|---|---|---|
| **7-day retention** (primary) | 19.02% | 18.20% | **−0.82pp** [−1.33, −0.31]; bootstrap [−1.35, −0.32] | 0.0016 |
| 1-day retention | 44.82% | 44.23% | −0.59pp [−1.24, +0.06]; bootstrap [−1.25, +0.06] | 0.074 (Holm 0.15) |
| Game rounds in 14 days, mean | 52.46 | 51.30 | −1.16 [−3.72, +1.40] | 0.38 (Holm 0.38) |
| Game rounds, median | 17 | 16 | −1 [−1, 0], bootstrap | |
| Never played a round (guardrail) | 4.33% | 4.52% | +0.19pp [−0.08, +0.46], limit +1.0pp | ok |

- **Decision: KILL, keep the gate at level 30.** No SRM at the 0.001 threshold, both arms past the 24,641 players they needed, the guardrail held, and the primary's interval is entirely below zero, so neither SHIP nor ITERATE applied. Relative to level 30 that's 4.3% fewer players back on day 7 (1.7% to 6.9%).
- **One outlier, kept in.** Player 6390605 (`gate_30`) logged 49,854 rounds in 14 days, 3,561 a day; the next-highest player has 2,961 and the 99.9th percentile is 1,074. Without them, the game-rounds difference goes from −1.16 (p = 0.38) to −0.04 (p = 0.95). That's a sensitivity check and decides nothing; the primary can't be moved by one player.
- **No CUPED.** Players were randomized at install, so there's no pre-experiment behavior to adjust with, and the in-test metrics could be moved by the gate.

### EXP-001 interim read

- **REAL: StudySprint live data, N = 0, underpowered (needs 1,377 per arm).** The live site has no PostHog key yet, so nothing has been collected.
- **Underpowered, plainly:** at about 5 new users a day, the 8-week cap ends near 140 per arm. At that size the test catches the planned +5-point lift only 14.5% of the time, and the smallest lift it would catch 80% of the time is 16.2 points. A non-significant live result won't mean Quick Start doesn't work, and a significant one would most likely overstate the lift. The live run proves the plumbing; the decision rule will call it UNDERPOWERED and the product stays on control.
- **SYNTHETIC full-size run** (seed 4, 3,581 users, true effect +5.0 points): SHIP, +9.9pp [+6.5, +13.4]. That's the Day 5 example, one draw that overshoots the truth; over 40 seeds the readout averaged +5.12.

### Checks

| Check | Result |
|---|---|
| `uv run pytest` | Pass, 194 tests (167 before) in 64 s. New: REAL labels with N and "underpowered"; bootstrap of mean and median; proportion guardrails; interim reads at any N that decide nothing; the Cookie Cats loader (bad columns, duplicates, flags), the outlier check and the readout on a built file; the real CSV against its published numbers; the dashboard's data layer against Day 3's and Day 5's numbers; the sample-size calculator against the power module; the metric tree against METRICS.md; every page run headless with Streamlit's AppTest, each with its badge; the Experiments page through all three choices and the calculator; the saved EXP-000 readout against a fresh read of the CSV. CI has no CSV, so the two tests that need it skip there. |
| `ruff check`, `ruff format --check` | Clean. |
| Dashboard in a browser | All five pages in light mode and the Experiments page in dark, at 1400 px: no errors, every chart drawn, every badge present. |
| Kaggle CSV and `.env` | Neither is tracked (`data/raw/*.csv` and `.env` are gitignored). |

### Decisions

- **Everything set after seeing the data is marked in EXP-000**, and the memo names the one choice that could have changed the answer: with an MDE below 0.75 points the read would have needed more players than the smaller arm has, and it would have said UNDERPOWERED instead of KILL.
- **Outliers are reported, not dropped.** The analysis of record keeps every player; the cap only decides who gets listed and the with/without comparison.
- **The dashboard runs with no data.** With no warehouse it builds the synthetic run, and without the CSV it shows the saved EXP-000 readout, which a test keeps equal to a fresh read.
- **An uploaded CSV gets its required N from its own control arm**, so the readout says whether that file could detect the MDE, not what a plan would have said.
- **Streamlit is a uv dependency group installed by default**, so CI runs the dashboard tests and Community Cloud gets the same locked versions.

### Worth knowing

- **Cookie Cats' SRM p = 0.0086 passes at 0.001 but would fail at 0.01.** The arms differ by 789 players. The file doesn't say why; it's in the memo's risks.
- **The effect is small in points and not in share**: under one point of 7-day retention, but 4.3% of the players who'd otherwise have stayed.
- **The deployed dashboard can't show live StudySprint data.** The warehouse is local, so a Community Cloud app shows the synthetic run and EXP-001's REAL tab at N = 0.

### Open

- **PostHog by hand**, still: the `phc_` key as the `VITE_POSTHOG_KEY` repository variable plus a deploy rerun, "Discard client IP data", then create and launch the experiment. Set `launch:` in EXP-001.yaml on launch day.
- The personal API key and project ID in `.env` for `liftlab export-posthog`.
- Optional: deploy the dashboard to Community Cloud (steps in the README).

### Next: Day 7

The last day. EXP-001 can't collect a single real user until the PostHog key is in.

## Day 7, 2026-11-01: case study, one CI workflow, v1.0.0

LiftLab is finished at v1.0.0. The README is now a case study, CI checks the analysis and the app on every push, and the repo has a description, topics, a contributing guide and issue templates. Labels stay as before: Cookie Cats numbers are **REAL**, StudySprint's live data is **REAL** with N = 0, and every other product and simulation number is **SYNTHETIC**.

### Done

- **One CI workflow.** `.github/workflows/ci.yml` replaces `analysis.yml` (a rename, agreed with Arnab, so its history carries over). Two jobs on every push and pull request: `analysis` (uv sync, ruff, ruff format, pytest) and `app` (npm ci, a new `typecheck` script, vitest, build). The simulation tests run small, about a minute; the full hour-long proofs stay a manual `liftlab proofs`. The two tests that need the Kaggle CSV skip in CI. `deploy-app.yml` is unchanged.
- **The README as a case study**, in this order: the pitch and links, a 90-second summary, the product and its North Star with the metric-tree image, what the data showed (SYNTHETIC funnel and retention; REAL N = 0), EXP-001 and EXP-000, the statistical proofs with their charts, key decisions and trade-offs, quickstart, a Mermaid architecture diagram, the tech stack, Now/Next/Later and limitations. Badges for CI, the deploy, the release and the license.
- **ADRs 0002 to 0004** in `docs/decisions/`, recording decisions made on Days 1 to 6 and dated when they were made: anonymous analytics with privacy in code, validating the statistics where the answer is known, and a fixed read with the mSPRT only for monitoring. Each says it was recorded today and which log it comes from.
- **EXP-001's interim readout gained a recommendation**, so both experiments have a decision memo: launch EXP-001 to prove the plumbing, and don't ship or kill Quick Start on its result.
- **Repo polish.** Description and the eight topics set with `gh repo edit` (product-management, ab-testing, experimentation, product-analytics, posthog, growth, cuped, sequential-testing). `CONTRIBUTING.md` with setup, the checks CI runs and the project's rules. Three issue forms: a StudySprint bug, a number that looks wrong (asks whether it's REAL or SYNTHETIC), and an experiment idea in the backlog's hypothesis format.
- **[docs/RESUME.md](RESUME.md)**: three sets of resume bullets (product, data science, engineering), a two-sentence pitch, five likely interview questions with answer outlines, and a table of every quotable number with its label and source.
- **Version 1.0.0** in `analysis/pyproject.toml`, `liftlab.__version__` and `app/package.json`, then the `v1.0.0` tag and a GitHub release.

### History check before tagging

Every commit on every branch (60, through this entry) was checked before the tag:

| Check | Result |
|---|---|
| Files ever added matching `.env`, `*.csv`, `*.duckdb`, `.wal`, `.parquet`, `.sqlite`, `.pem`, `.key` or `secrets` | Only `.env.example` and `app/.env.example`. |
| Every version of those two templates | Empty values, plus the public PostHog host URLs. |
| Token patterns in every revision (`phc_`, `phx_`, `ghp_`, `github_pat_`, `AKIA`, private-key headers, Slack and OpenAI-style keys) | None. |
| PostHog env vars assigned a value anywhere | Only placeholders in ANALYTICS.md and an empty test fixture. |
| Cookie Cats rows (`<id>,gate_30,...`) in any revision | None. |
| Largest blob ever | 494 kB, a dashboard screenshot. |

### Checks

| Check | Result |
|---|---|
| `uv run pytest` | Pass, 194 tests in 64 s (CI: 192 passed, 2 skipped without the CSV). |
| `ruff check`, `ruff format --check` | Clean. |
| `npm run typecheck`, `npm test`, `npm run build` | Pass: 63 tests; 16.6 kB JS, 6.2 kB gzipped. |
| CI | Green on every Day 7 push, both jobs: [run 41333667016](https://github.com/singha105/liftlab/actions/runs/41333667016) was the first. The deploy that the `package.json` change triggered also passed. |
| Live StudySprint | https://singha105.github.io/liftlab/ returns 200. |
| Links | Every relative link and heading anchor in the README and docs resolves (checked with a script), and all 15 external URLs return 200. |
| README on GitHub | Rendered and looked at: images load in light and dark, and the Mermaid diagram was redrawn top-down after the first version came out clipped. |

### Decisions

- **Replace `analysis.yml` instead of running both.** Two workflows would have run the same tests twice on every push.
- **No `slow` marker.** The slowest test takes about 5 s and the whole suite about a minute, so CI runs all of it. "Fast simulation tests only" is met by keeping the full-size proofs out of pytest, as they already were.
- **The ADRs record decisions; they don't invent them.** Each one cites the day it was made, and nothing in them is new.
- **No resume claim about real users.** StudySprint has none yet, so the bullets claim what was built and measured: the plan, the proofs (SYNTHETIC) and the Cookie Cats call (REAL).

### LiftLab at v1.0.0

- **Product:** StudySprint, live on GitHub Pages, 6.2 kB of gzipped JS, anonymous analytics wired up and waiting on a PostHog key.
- **Metrics:** a North Star (weekly completed sessions) with an exact three-factor identity, a metric tree, a tracking plan enforced by tests, and seven SQL models checked against ground truth.
- **Experiments:** EXP-001 pre-registered before its code (needs 1,377 per arm, not reachable at about 5 users a day), and EXP-000's real decision on 90,189 players: keep the gate at level 30.
- **Statistics:** SRM, z and Welch, delta method, bootstrap, CUPED, mSPRT and Holm, each cross-checked and proven on simulations (SYNTHETIC: A/A 5.8%, peeking 27.3% vs mSPRT 1.7%, CUPED −22% variance, power 81.8%).
- **Tests:** 194 in Python and 63 in the app.

### Open

- **PostHog by hand**: the `phc_` key as the `VITE_POSTHOG_KEY` repository variable plus a deploy rerun, "Discard client IP data", then create and launch EXP-001 and set `launch:` in EXP-001.yaml. The 8-week limit runs from that day.
- The personal API key and project ID in `.env` for `liftlab export-posthog`.
- Optional: deploy the dashboard to Streamlit Community Cloud (steps in the README).
