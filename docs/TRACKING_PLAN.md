# StudySprint tracking plan

Version 3, 2026-10-30

This is every event StudySprint sends. If an event or property isn't in this file, the app doesn't send it. In code the plan is the `PLAN` object in [`app/src/analytics.ts`](../app/src/analytics.ts): each event gets a typed tracking function derived from it, so an unplanned event or property fails the TypeScript build, and a test fails if `PLAN` and this file disagree.

## Conventions

- Event names are `object_action` in snake_case, verb in the past tense: `session_started`, not `start_session` or `SessionStarted`.
- Property names are snake_case. Types are `string`, `int`, `bool`, `uuid` (a random v4 UUID string) and `enum(a, b, c)` (one of the listed values).
- Durations put the unit in the name: `_minutes`, `_seconds`, `_ms`.
- Booleans read as yes/no questions: `goal_set`, `is_first_open`.

## Properties on every event

Registered once at startup as PostHog super properties, so they ride along on every event below.

| Property | Type | Notes |
|---|---|---|
| `app_version` | string | Short git SHA of the deployed build, or `dev`. |
| `experiment_key` | string | Key of the experiment currently running, or `none`. |
| `variant` | enum(control, test, none) | This user's arm in that experiment, or `none`. |
| `is_demo` | bool | The page was opened with `?demo=1`. Analysis drops these events. |

PostHog adds its standard properties too: the anonymous `distinct_id`, the timestamp, and browser, OS, device, screen and page-URL fields such as `$browser`, `$os`, `$device_type` and `$current_url`. Once flags have loaded it also adds `$active_feature_flags` and one `$feature/<flag>` property per flag, such as `$feature/exp-001: test`; PostHog's experiment view reads the arm from `$feature/exp-001` on `experiment_exposed`. We keep those, minus IP addresses, timezone, query strings and person properties (see the privacy rules).

## Events

| Event | Trigger | Properties | Used by |
|---|---|---|---|
| `app_opened` | The app has rendered and the timer controls respond. Once per page load. | `is_first_open:bool`, `load_ms:int`, `referrer_type:enum(direct, search, social, other)`, `current_streak_days:int` | New users, start of the 24 h activation window, page load guardrail |
| `session_started` | The user presses Start (or "Start another" on the completion screen). A reload that resumes a running session doesn't fire it again. | `session_id:uuid`, `planned_minutes:enum(15, 25, 50)`, `goal_set:bool`, `start_method:enum(preset, quick_start)`, `session_number:int` | Active users (DAU, WAU), sessions per active user, retention, start rate, denominator for completion and abandon rates |
| `session_completed` | The timer reaches 0 (in a background tab, on the first tick after that), or the user answers "Yes, count it" in the away check. | `session_id:uuid`, `planned_minutes:enum(15, 25, 50)`, `actual_minutes:int`, `pause_count:int`, `goal_set:bool`, `current_streak_days:int`, `is_first_completion:bool`, `completed_while_away:bool` | North Star, completion rate, activation, weekly focus minutes |
| `session_abandoned` | The user confirms "Give up"; or answers "No" in the away check; or on the next app open the app finds a session that sat paused, or ran out unanswered, for over 24 h. | `session_id:uuid`, `planned_minutes:enum(15, 25, 50)`, `elapsed_seconds:int`, `pause_count:int`, `goal_set:bool`, `reason:enum(user_ended, page_closed, stale)` | Abandon rate guardrail, completion rate |
| `streak_viewed` | The streak is shown: automatically on the completion screen, or when the user opens it from the home screen. | `current_streak_days:int`, `longest_streak_days:int`, `surface:enum(completion_screen, home)` | The "see streak" step of the loop; driver of weekly returning users |
| `weekly_summary_viewed` | The weekly summary is shown: automatically on the first open of a new local week (for someone with at least one completed sprint), or when the user opens it. | `sessions_completed_week:int`, `focus_minutes_week:int`, `opened_by:enum(new_week, user)` | Driver of returning users and sessions per active user |
| `experiment_exposed` | The first time a user reaches the screen where the arms differ. Fires for control and test alike, once per user per experiment. | `experiment_key:string`, `variant:enum(control, test)` | Who is in each experiment, sample ratio mismatch check |

Property notes:

- `session_id` is generated on Start and joins a session's start to its end.
- `session_number` counts sessions started on this device, so 1 means the user's first session ever.
- `planned_minutes` is one of the three presets. Focus time is `planned_minutes`.
- `actual_minutes` is wall-clock time from Start to the moment the timer reached zero, pauses included.
- `elapsed_seconds` is focus time before the session ended, pauses excluded and capped at the planned length. It's in seconds because a lot of give-ups happen in the first minute.
- `completed_while_away` is true when the timer ran out while no StudySprint page was open and the user confirmed afterwards that they finished. The event's timestamp is when the timer reached zero, not when they answered.
- `load_ms` runs from navigation start to the moment the timer controls respond, measured with `performance.now()`.
- `referrer_type` is worked out in the browser from the referring domain.
- `current_streak_days` on `session_completed` includes the session that just finished.
- `sessions_completed_week` and `focus_minutes_week` describe the week the summary shows: last week when it opens on its own at the start of a new week, the current week so far when the user opens it.
- **Demo mode** (`?demo=1`) runs one second per timer minute and keeps its own local storage, so demo sessions never touch a real streak. Durations in demo events are scaled the same way (a 25-second demo sprint reports `planned_minutes: 25`), and `is_demo` is true.

## Session lifecycle

Every `session_started` ends in exactly one of these:

1. `session_completed`
2. `session_abandoned`, with reason `user_ended`, `page_closed` or `stale`
3. Nothing, if the student never opens StudySprint again. The warehouse treats a session with no end event 24 hours after its start as abandoned, with reason `no_end_event`.

A running session is saved to localStorage, so a reload or a crashed tab resumes it. If the timer ran out while no page was open (a closed tab, or a phone that discarded it in the background), the next open asks "Did you stay with it until the end?": yes is a completion with `completed_while_away: true`, no or Escape is `page_closed`. Phones discard background tabs often enough that silently counting these as abandoned would punish exactly the students who put the phone down to study.

## Experiment exposure

- `experiment_exposed` fires when the screen that differs between arms renders, not when the flag is evaluated. A user who never reaches that screen isn't in the analysis.
- It fires once per user per experiment; the app keeps the arm in localStorage and registers `experiment_key` and `variant` as super properties from then on, on every later visit too. The analysis still uses each user's first exposure, in case a cleared cache sends it twice.
- The flag is read through `getVariant()` in `analytics.ts` with `send_event: false`, so PostHog's own `$feature_flag_called` is never sent. Only a flag that loads within 1.5 seconds and says `control` or `test` gives the user an arm. Anyone else (no key, Do Not Track, opted out, blocked, slow network, flag missing) sees control and is never exposed, so a slow network can't quietly add people to the control arm.
- Users with Do Not Track or Global Privacy Control on never load PostHog, so they always get control and are never exposed.
- Demo mode is never enrolled. `?demo=1&variant=test` previews an arm locally without sending an exposure.

### EXP-001: Quick Start (`exp-001`)

Pre-registered in [experiments/EXP-001.md](experiments/EXP-001.md). The flag is read only on a device's first open. `experiment_exposed` fires once the flag has loaded, if the user is still on the untouched start screen: no session started, no length or goal picked. In test, that's the moment the start screen switches to the Quick Start button; in control nothing visible changes. A Quick Start session sends `session_started` with `start_method: quick_start`, `planned_minutes: 25` and `goal_set: false`. Test users keep the Quick Start screen on later visits until their first session starts.

## Privacy rules

These aren't preferences. The tests in `app/src/analytics.test.ts` cover rules 1 to 3, 5 and 7.

1. **No personal data and no free text.** No names, emails, phone numbers or anything the user typed. The session goal is picked from preset chips and never leaves the device; events carry `goal_set: true`, never the goal. The only text-valued properties are generated IDs and build metadata (`session_id`, `experiment_key`, `app_version`).
2. **Anonymous IDs only.** The ID is the random one PostHog generates on the first visit, stored with `persistence: 'localStorage'`, so there are no cookies. The app never calls `identify()` and never sets person properties, so with `person_profiles: 'identified_only'` no person profiles are created.
3. **Respect Do Not Track and Global Privacy Control.** If `navigator.doNotTrack === '1'` or `navigator.globalPrivacyControl === true`, PostHog isn't loaded at all: no events and no feature-flag requests. The app works the same and shows the control experience. `respect_dnt: true` is set as well, as a backstop.
4. **No IP addresses.** "Discard client IP data" is turned on in the PostHog project settings. The old `ip: false` init option is deprecated and does nothing, so the project setting is the only real control.
5. **Nothing captured implicitly.** Autocapture, pageviews, page-leaves, rage and dead clicks, heatmaps, web vitals, exception capture, session recording, surveys, web experiments, product tours and conversations are all switched off, and `disable_external_dependency_loading` stops PostHog loading extra scripts. As a backstop, `before_send` drops any event that isn't in this plan.
6. **No query strings, location or person properties.** `before_send` strips query strings and fragments from every URL-valued PostHog property (`$current_url`, `$referrer`, `$session_entry_url` and so on), drops `$timezone` and `$timezone_offset`, and removes `$set` and `$set_once`.
7. **An off switch that sticks.** The footer's "Turn off analytics" calls `opt_out_capturing()` and saves the choice. On later visits PostHog isn't loaded at all, because PostHog's own opt-out still lets feature-flag requests through.
8. **Exports stay local.** Event exports go into `data/`, which is gitignored. Synthetic events are never sent to PostHog; they exist only in the local DuckDB file, tagged `source = 'synthetic'`.

## Changing this plan

Change this file in the same commit as `PLAN` in `analytics.ts`, bump the version at the top and add a changelog line. The parity test fails until the two agree.

### Changelog

- **v3, 2026-10-30**: EXP-001. A user gets an arm only from a loaded `control` or `test` flag; before, anything short of `test` counted as control, which would have put slow-network users into the control arm. Exposure rules for `exp-001`, the demo preview, and PostHog's `$feature/<flag>` properties are written down. No events or properties changed.
- **v2, 2026-10-30**: built on Day 2. `planned_minutes` is now `enum(15, 25, 50)`, because custom lengths were dropped. `start_method` loses `custom`. New super property `is_demo`; `variant` is now an enum. New `completed_while_away` on `session_completed`, and `page_closed` now means the user said no in the away check. The goal is chosen from chips. Weekly summary properties and `elapsed_seconds` are defined precisely. `before_send` drops unplanned events.
- **v1, 2026-10-29**: first version, seven events.
