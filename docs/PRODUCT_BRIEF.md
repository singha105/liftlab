# StudySprint product brief

StudySprint is a focus timer for students. You pick a session length, optionally note what you're working on, and study until the timer runs out. Finishing a session extends your streak, and once a week you get a short summary of what you got done.

It's a static web app on GitHub Pages. There's no backend and no account; everything the app remembers lives in the browser's localStorage.

## Who it's for

A university student who studies most days, usually on a laptop, often in a library or a shared room. Time isn't the problem. Starting is: the first ten minutes of a study block go to email, picking a playlist, re-sorting notes. And once they do start, staying on one thing is the second problem.

They've tried timers. A bare Pomodoro clock gives them nothing to come back for. The bigger productivity apps want an account, a task list and a setup session before the first minute of focus.

## Job to be done

> When I sit down to study and can't get going, help me commit to one short, defined block of focus, so I make real progress and can see that I'm keeping up.

## Core loop

```
set a session → focus → complete → see streak → come back
```

1. **Set a session.** Pick 15, 25 or 50 minutes and, if you like, tap what you're working on (Reading, Problem set, and so on).
2. **Focus.** The timer takes over the page with almost nothing else on it. You can pause, resume or give up.
3. **Complete.** When the timer reaches zero, the session counts.
4. **See streak.** The completion screen shows your streak: consecutive local calendar days with at least one completed session.
5. **Come back.** The streak and the weekly summary are the reasons to open it again tomorrow.

Each step maps to a metric in [METRICS.md](METRICS.md) and an event in [TRACKING_PLAN.md](TRACKING_PLAN.md).

## v1 scope

In:

| Feature | What it does |
|---|---|
| Timer | 15, 25 or 50 minutes. Pause, resume, give up. Counts from timestamps, so a background tab or a sleeping laptop doesn't drift, and a reload resumes the running session. If the timer ran out while the page was closed, the next visit asks whether you finished. |
| Session goal | Optional, picked from preset chips, so there's no free-text box. Shown while the timer runs; it stays on the device and only "a goal was set" reaches analytics. |
| Completion | The timer reaching zero marks the session done and shows the completion screen. |
| Streak | Current and longest streak, in local calendar days. |
| Weekly summary | Sessions completed and minutes focused this week, next to last week. Opens by itself on the first visit of a new week. |
| Demo mode | `?demo=1` runs every timer in seconds, for testing and screen recordings, with separate storage so it never touches a real streak. |

Out, and why:

- **Accounts.** Sign-up is exactly the friction we're trying to remove, and it would mean storing emails.
- **Sync across devices.** Needs accounts and a backend. In v1 a streak belongs to one browser.
- **Social** (friends, leaderboards, sharing). Comparison isn't the job, and it needs real identities.
- **Custom lengths.** Three presets keep the first screen to one decision; a custom length can come back if data asks for it.
- Also out: push notifications, task lists, calendar or LMS integrations, sounds and music, a paid plan.

## Constraints

- $0 to run: GitHub Pages for hosting, PostHog's free tier for analytics and feature flags, no servers.
- Analytics are anonymous by design. The rules are in [TRACKING_PLAN.md](TRACKING_PLAN.md#privacy-rules).
- It has to load fast on campus Wi-Fi. Page load time is a guardrail metric, so a heavy framework would need a reason.

## Risks we're accepting

- **Device-bound identity.** Clearing site data, a private window or a second laptop all look like a new user. That inflates new-user counts and understates retention. We'll report numbers with that caveat instead of adding accounts to fix it.
- **Little real traffic.** This is a portfolio build, so organic usage will be small. Day 3 adds a synthetic event generator that follows the tracking plan exactly, so the analysis has volume. Every readout says which numbers come from real users and which from simulation.
- **No revenue.** v1 is free. If it ever earned money, the likely shape is a paid tier for sync and longer history, bought by people who already use it every week. That's why retention stands in for revenue when we pick metrics.
