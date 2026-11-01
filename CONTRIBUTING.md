# Contributing

LiftLab is a portfolio project, but issues and pull requests are welcome: a bug in StudySprint, a number that looks wrong, or an experiment idea. Use the [issue templates](https://github.com/singha105/liftlab/issues/new/choose).

## Setup

You need Node 20.19+ or 22.12+ for the app and [uv](https://docs.astral.sh/uv/) for the analysis. Nothing needs an account or a key: without a PostHog key the app sends nothing, and the analysis runs on simulated data.

```bash
cd app && npm install && npm run dev
```

```bash
cd analysis && uv sync && uv run liftlab load --source synthetic && uv run liftlab build
```

## Before you open a pull request

CI runs these on every push and pull request, so run them first:

```bash
cd analysis && uv run ruff check . && uv run ruff format --check . && uv run pytest
```

```bash
cd app && npm run typecheck && npm test && npm run build
```

## Rules the project keeps

- **Definitions change in the docs first.** A metric's definition lives in [METRICS.md](docs/METRICS.md) and the SQL follows it. Events live in [TRACKING_PLAN.md](docs/TRACKING_PLAN.md) and the `PLAN` object in `app/src/analytics.ts`; a test fails if the two disagree, so change them together.
- **No personal data.** Only planned events, no free text, no session recording, no identifiers beyond PostHog's anonymous ID. A new event or property is a tracking-plan change.
- **Every number says where it came from.** Tables, charts and docs label numbers REAL (real people) or SYNTHETIC (the simulator). Never present simulated data as real usage.
- **Pre-registrations are fixed once data arrives.** The primary metric, sample size and decision rule in a plan like [EXP-001](docs/experiments/EXP-001.md) don't change after launch. Changes before launch go in its Amendments section, dated.
- **Statistics get checked.** Every statistical function needs a test against a known value, a reference library (scipy, statsmodels), or a simulation property.
- **Nothing private or raw gets committed.** `.env`, the Kaggle CSV and DuckDB files are gitignored; keep them that way.

## Commit messages

Short and in the imperative, with a type and, where it helps, the part of the repo: `feat(analysis): ...`, `fix(app): ...`, `test(app): ...`, `docs: ...`, `ci: ...`.

By contributing, you agree that your work is licensed under the [MIT License](LICENSE).
