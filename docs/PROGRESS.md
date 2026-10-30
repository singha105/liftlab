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
