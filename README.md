# LiftLab

LiftLab is a growth-analytics project built around a small, real product. StudySprint is a focus timer for students: it runs on GitHub Pages and sends anonymous events to PostHog. Around it sits what a growth team would use to improve it: a North Star and metric tree, a tracking plan, a DuckDB warehouse with SQL funnels and retention, pre-registered A/B tests behind feature flags, and a Python stats library (SRM checks, bootstrap, CUPED, sequential testing) that's also used to re-analyze the public Cookie Cats A/B test. It all runs on free tiers.

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
├── .env.example    PostHog settings for event export (copy to .env)
└── LICENSE         MIT
```

## Running it

The app needs Node 20+:

```bash
cd app && npm install && npm run dev
```

The analysis package needs [uv](https://docs.astral.sh/uv/):

```bash
cd analysis && uv sync && uv run pytest
```

## Status

Day 1 of 7: strategy docs and scaffold. See [docs/PROGRESS.md](docs/PROGRESS.md).

## License

[MIT](LICENSE)
