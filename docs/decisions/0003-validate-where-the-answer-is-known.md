# 0003: Validate the statistics where the answer is known; the live test proves the plumbing

- Status: accepted
- Date: 2026-10-30
- Decider: Arnab Singh
- Recorded: 2026-11-01, from the Day 4 log in [PROGRESS.md](../PROGRESS.md) and [EXP-001](../experiments/EXP-001.md#duration-and-feasibility)

## Context

EXP-001, Quick Start for new users, needs 1,377 exposed users per arm to detect a +5-point lift in activation from a 30% baseline (alpha 0.05, power 0.80). StudySprint is a portfolio project with no marketing, and about 5 eligible new users a day is a generous guess. At that rate the test needs 551 days.

## Options considered

1. Run the live test until it reaches 1,377 per arm, about a year and a half.
2. Run it for a fixed time and act on whatever it shows.
3. Cap the live run, never act on an underpowered result, and check the statistics where the true answer is known: a simulator with ground truth, and a large public A/B test.

## Decision

Option 3. The live run is capped at 8 weeks, about 140 users per arm, and the pre-registered decision rule calls anything short of 1,377 per arm UNDERPOWERED, so the product stays on control. The statistics are checked on thousands of simulated experiments with a known effect, and on the public Cookie Cats test with 90,189 players ([EXP-000](../experiments/EXP-000-memo.md)).

## Why

- At 140 per arm the test detects the planned +5-point lift 14.5% of the time; the smallest lift it would catch 80% of the time is 16.2 points. Acting on that would mean shipping on noise or killing a feature that works.
- Only a simulator knows the true effect, so it's the only way to measure a test's false-positive rate and power directly. On Day 5 that gave 5.8% false positives on 1,000 A/A experiments and 81.8% power on 1,000 experiments with a true +5 points (synthetic).
- The live run still answers questions the simulator can't: does the flag split real browsers about 50/50, does exposure fire once, do Quick Start sessions arrive tagged, and does the export reach the warehouse?

## Consequences

- LiftLab makes no claim about how well Quick Start works for real students.
- The simulator's numbers are only as good as its assumptions, which came from the experiment backlog. It shows the SQL and the statistics are right, not that students behave this way.
- The Cookie Cats plan was written after the data was public, which [EXP-000](../experiments/EXP-000-cookie-cats.md) says up front.

## Revisit if

- Eligible traffic reaches about 40 new users a day, when the test would take 69 days.
