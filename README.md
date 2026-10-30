# LiftLab

LiftLab is a growth-analytics project built around a small, real product. StudySprint is a focus timer for students: it runs on GitHub Pages and sends anonymous events to PostHog. Around it sits what a growth team would use to improve it: a North Star and metric tree, a tracking plan, a DuckDB warehouse with SQL funnels and retention, pre-registered A/B tests behind feature flags, and a Python stats library (SRM checks, bootstrap, CUPED, sequential testing) that's also used to re-analyze the public Cookie Cats A/B test. It all runs on free tiers.

**Try it:** [singha105.github.io/liftlab](https://singha105.github.io/liftlab/). Add [`?demo=1`](https://singha105.github.io/liftlab/?demo=1) to run every timer in seconds instead of minutes.

## Privacy

StudySprint sends anonymous usage analytics only: no account, no names or emails, nothing you type, no session recording, no IP addresses. Do Not Track and Global Privacy Control are respected (PostHog isn't even loaded), and the footer has a switch to turn analytics off. Exactly which events are sent is listed in the [tracking plan](docs/TRACKING_PLAN.md), and a test fails if the code and that list disagree.

## Layout

```
liftlab/
├── app/            StudySprint: Vite + TypeScript, deployed to GitHub Pages
├── analysis/       Python package `liftlab`: warehouse, metric SQL, stats library, tests
├── data/           local only, gitignored: raw downloads, event exports, DuckDB files
│   └── raw/
├── docs/
│   ├── PRODUCT_BRIEF.md       who it's for, core loop, v1 scope
│   ├── METRICS.md             North Star, metric tree, exact definitions
│   ├── TRACKING_PLAN.md       every event, its properties, privacy rules
│   ├── EXPERIMENT_BACKLOG.md  ICE-ranked hypotheses
│   ├── decisions/             decision records
│   └── PROGRESS.md            day-by-day log
├── .github/workflows/deploy-app.yml   test, build and deploy app/ to Pages
├── .env.example    PostHog settings for event export (copy to .env)
└── LICENSE         MIT
```

## Running it

The app needs Node 20.19+ or 22.12+:

```bash
cd app && npm install && npm run dev
```

```bash
cd app && npm test
```

Analytics stay off locally unless you copy `app/.env.example` to `app/.env.local` and add a PostHog project key. The deployed build gets `VITE_POSTHOG_KEY` and `VITE_POSTHOG_HOST` from repository variables in [the deploy workflow](.github/workflows/deploy-app.yml).

The analysis package needs [uv](https://docs.astral.sh/uv/):

```bash
cd analysis && uv sync && uv run pytest
```

## Status

Day 2 of 7: StudySprint is live and instrumented. See [docs/PROGRESS.md](docs/PROGRESS.md).

## License

[MIT](LICENSE)
