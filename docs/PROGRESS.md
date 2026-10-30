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
