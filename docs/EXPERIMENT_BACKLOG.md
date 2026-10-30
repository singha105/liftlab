# Experiment backlog

## The weakest input

StudySprint has no data yet, so this ranking runs on assumptions. They're written down here so that real traffic can prove them wrong.

| Input | Assumed baseline | Reasoning |
|---|---|---|
| Activation rate | ~30%: about half of new users start a session, and about 60% of those finish it within 24 h | A first-time visitor has to pick a length, maybe type a goal, press Start, then stay put for 15 to 50 minutes, all before the product has proven anything to them. |
| D7 retention | ~15% | Most of this loss is inherited. Users who never finish a first session rarely come back. |
| Sessions per active user | ~4 a week | People who return tend to use it on study days, which aren't every day. |
| Completion rate, all sessions | ~75% | Returning users chose to come back, so they finish more often than first-timers do. |

**We're targeting activation.** D7 looks lower, but it's mostly downstream: fix activation and D7 rises with it, while the reverse isn't true. Activation is also where the gap is largest; at 30%, seven in ten new users get nothing out of their first visit. And it reads fastest. Activation is settled 24 hours after a user arrives, while D7 takes eight days and D28 a month. In a seven-day build, that decides what we can test at all.

One caveat: the Day 3 generator is built from these same assumptions, so it can't confirm them. Only real usage can, and when there's enough of it this list gets re-ranked.

## Scoring

ICE: impact, confidence and ease, each scored 1 to 10 and summed (30 max).

- **Impact.** How far activation could move if the idea works. That depends on which leak it targets (we assume about 50% of new users are lost before starting and 40% of starters before finishing) and on how many new users see it.
- **Confidence.** How much evidence backs the idea. 8+ is a well-known pattern we'd bet on, 5 is plausible reasoning, 3 or less is a hunch.
- **Ease.** Effort to build and instrument. 10 is under an hour, 8 half a day, 6 a day, 4 two to three days.

Ties go to the higher impact score.

Every item has the same primary metric (activation rate) and the same guardrails (abandon rate and page load time, defined in [METRICS.md](METRICS.md#guardrails)).

## Ranked hypotheses

### 1. Quick Start for first-time visitors

**ICE 8 / 6 / 9 = 23. This is the Day 4 experiment.**

> Because we see that a first-time visitor has to make three choices (length, optional goal, Start) before the timer runs, and starting is where we expect the biggest loss (about half of new users never start), we believe a one-click "Start a 25-minute focus" button for new users will increase activation rate.

- **Change.** New users, meaning no previous session on this device, see one large Quick Start button. The length picker and goal field fold away under "Customize". Returning users see the normal screen.
- **Why 25 minutes.** Control also has 25 preselected, so the only difference between the arms is the number of decisions. Session length gets its own test in #2.
- **Exposure.** The first render of the start screen for a new user, in both arms.
- **Secondary metrics.** Start rate, D1 retention.
- **Main risk.** People start sessions they never meant to finish. That would show up in the abandon-rate guardrail.
- **Size.** Detecting a lift from 30% to 35% (two-sided, α = 0.05, 80% power) takes about 1,380 new users per arm. Day 4 redoes this properly in the pre-registration.

### 2. Shorter first sprint

**ICE 5 / 6 / 10 = 21**

> Because we see that the first session is also the activation test, and 25 minutes is a lot to ask of someone who opened the app because they couldn't get started, we believe preselecting 15 minutes (the shortest preset) for a new user's first session will increase activation rate.

- **Change.** A new user's length picker starts on 15 instead of 25. After the first session it remembers whatever they last chose, as it does today.
- **Watch.** The length mix and second-session completion. A short first session could teach people that short is normal, which is the farming risk noted in ADR 0001.
- **Updated 2026-10-30.** This was a 10-minute default; v1 shipped with presets only, so the test now uses the 15-minute preset, with impact cut by one point because the change is smaller.

### 3. Show the streak before it exists

**ICE 5 / 5 / 9 = 19**

> Because we see that the streak, our main reason to come back, stays hidden until after the first completion, which leaves a new user no reason to finish beyond the session itself, we believe showing "Finish this sprint to start your streak" on a new user's running timer will increase activation rate.

- **Change.** A single line under the timer during a new user's first session.
- **Watch.** D7 retention, since this also sets up the habit hook.

### 4. Countdown in the tab title

**ICE 4 / 5 / 10 = 19**

> Because we see that once a student switches tabs the timer disappears, so nothing reminds them a session is running, we believe showing the time left in the tab title ("18:42 · StudySprint") during a session will increase activation rate by raising first-session completion.

- **Change.** `document.title` updates once a second while a session runs.
- **Note.** This would help completion for everyone, not only new users, so it's worth shipping even if the activation effect turns out small. It ranks below #3 only on the tie-break.

### 5. Show how close you are before giving up

**ICE 4 / 5 / 9 = 18**

> Because we see that the "Give up this sprint?" dialog says nothing about how far along the student is, so quitting at minute 22 of 25 feels the same as quitting at minute 2, we believe showing the time left and the progress ring in that dialog during a new user's first session will increase activation rate.

- **Change.** The dialog reads "Only 3:12 left. Give up anyway?" with the ring, instead of "It won't count toward your streak."
- **Watch.** `elapsed_seconds` on give-ups; the effect should show up as fewer late give-ups, not early ones.

### Retired: goal chips instead of a text box

This was #5 (ICE 16). Day 2 shipped chips as the v1 design, because free text was ruled out for privacy, so there's nothing left to test. Tracking a `goal_category` enum from the chips is still possible later, with a tracking-plan change first.

## Parked

These are aimed at other inputs. They'll be scored when activation stops being the bottleneck.

- A calendar file (.ics) on the completion screen for "same time tomorrow", aimed at weekly returning users. It's generated in the browser, so no personal data is involved.
- A "your best day this week" line in the weekly summary, aimed at sessions per active user.
