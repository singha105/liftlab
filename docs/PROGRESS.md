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
