# 0002: Anonymous analytics, with privacy enforced in code

- Status: accepted
- Date: 2026-10-29, amended 2026-10-30
- Decider: Arnab Singh
- Recorded: 2026-11-01, from the Day 1 and Day 2 logs in [PROGRESS.md](../PROGRESS.md)

## Context

StudySprint needs product events to measure its North Star and run experiments, and PostHog's free tier provides events and feature flags at $0. PostHog's defaults capture far more than that: autocapture of clicks, pageviews, session recording, IP addresses and person profiles. The users are students using a study tool, often on shared or campus networks, and the brief rules out accounts.

## Options considered

1. PostHog with its defaults, filtering what we don't need later.
2. No analytics at all.
3. Only the events in the tracking plan, anonymous, with every privacy rule enforced in the app's code rather than left to settings.

## Decision

Option 3. StudySprint sends only the seven planned events with their typed properties. Autocapture, pageviews, page leave, heatmaps, exceptions, surveys and session recording are off. There's no `identify` or `alias`, so no person profiles. `before_send` drops anything not in the plan and strips query strings, the timezone and `$set` properties. Do Not Track, Global Privacy Control, a missing key or the footer's opt-out mean posthog-js is never downloaded.

## Why

- Data that's never collected can't leak or be misused, and the metrics don't need it.
- Rules in code are testable. The tracking plan is the `PLAN` object in `app/src/analytics.ts`, a test fails if it and [TRACKING_PLAN.md](../TRACKING_PLAN.md) disagree, and an unplanned property fails `tsc`.
- PostHog's own `opt_out_capturing` still calls `/flags` on the next load, and the `ip: false` init option is deprecated and does nothing. Neither could be relied on.

## Consequences

- **Identity is one browser.** Clearing site data, a private window or a second laptop all look like a new user, which inflates new users and understates retention. Trends matter more than levels.
- **Some users are missing, not filtered.** Do Not Track, GPC and ad-blocked visitors send nothing and can't be enrolled in experiments.
- **PostHog can't target "new users".** With no person profiles there's nothing to target on, so the app enforces EXP-001's eligibility itself, on a first open.
- Every new event or property is a tracking-plan change first.
- "Discard client IP data" is a PostHog project setting, which still has to be turned on by hand before the key goes live.

## Revisit if

- A later version adds accounts or sync, which changes what identity means and what data the product holds.
- Event volume approaches the PostHog free tier's monthly allowance.
