# StudySprint tracking plan

Version 1, 2026-10-29

This is every event StudySprint sends. If an event or property isn't in this file, the app doesn't send it. On Day 2 the plan becomes a typed `track()` wrapper: each event name maps to a TypeScript type with exactly the properties below, so an unplanned event or property fails to compile.

## Conventions

- Event names are `object_action` in snake_case, verb in the past tense: `session_started`, not `start_session` or `SessionStarted`.
- Property names are snake_case. Types are `string`, `int`, `bool`, `uuid` (a random v4 UUID string) and `enum(a, b, c)` (a string limited to those values).
- Durations put the unit in the name: `_minutes`, `_seconds`, `_ms`.
- Booleans read as yes/no questions: `goal_set`, `is_first_open`.

## Properties on every event

Registered once at startup as PostHog super properties, so they ride along on every event below.

| Property | Type | Notes |
|---|---|---|
| `app_version` | string | Short git SHA of the deployed build. |
| `experiment_key` | string | Key of the experiment currently running, or `none`. |
| `variant` | string | This user's arm in that experiment (`control` or `test`), or `none`. |

PostHog adds its own properties too: the anonymous `distinct_id`, the timestamp, `$browser`, `$os`, `$device_type`, `$current_url`, `$referrer` and `$lib`. We keep those, minus IP addresses and query strings (see the privacy rules).

## Events

| Event | Trigger | Properties | Used by |
|---|---|---|---|
| `app_opened` | The app has rendered and the timer controls respond. Once per page load. | `is_first_open:bool`, `load_ms:int`, `referrer_type:enum(direct, search, social, other)`, `current_streak_days:int` | New users, start of the 24 h activation window, page load guardrail |
| `session_started` | The user presses Start, from the length picker or a Quick Start button. A reload that resumes a running session doesn't fire it again. | `session_id:uuid`, `planned_minutes:int`, `goal_set:bool`, `start_method:enum(preset, custom, quick_start)`, `session_number:int` | Active users (DAU, WAU), sessions per active user, retention, start rate, denominator for completion and abandon rates |
| `session_completed` | The timer reaches 0. If the tab was in the background or the laptop asleep, it fires on the first tick after that. | `session_id:uuid`, `planned_minutes:int`, `actual_minutes:int`, `pause_count:int`, `goal_set:bool`, `current_streak_days:int`, `is_first_completion:bool` | North Star, completion rate, activation, weekly focus minutes |
| `session_abandoned` | The user confirms "End early", or on the next app open the app finds a session that ran out while its tab was closed, or one that has sat paused or unfinished for over 24 h. | `session_id:uuid`, `planned_minutes:int`, `elapsed_seconds:int`, `pause_count:int`, `goal_set:bool`, `reason:enum(user_ended, page_closed, stale)` | Abandon rate guardrail, completion rate |
| `streak_viewed` | The streak card is shown: automatically on the completion screen, or when opened from the home screen. | `current_streak_days:int`, `longest_streak_days:int`, `surface:enum(completion_screen, home)` | The "see streak" step of the loop; driver of weekly returning users |
| `weekly_summary_viewed` | The weekly summary is shown: automatically on the first open of a new local week, or when the user opens it. | `sessions_completed_week:int`, `focus_minutes_week:int`, `opened_by:enum(new_week, user)` | Driver of returning users and sessions per active user |
| `experiment_exposed` | The first time a user reaches the screen where the arms differ. Fires for control and test alike, once per user per experiment. | `experiment_key:string`, `variant:string` | Who is in each experiment, sample ratio mismatch check |

Property notes:

- `session_id` is generated on Start and joins a session's start to its end.
- `session_number` counts sessions on this device, so 1 means the user's first session ever.
- `actual_minutes` is wall-clock time from Start to completion, pauses included. Focus time is `planned_minutes`.
- `elapsed_seconds` is in seconds because a lot of abandons happen in the first minute.
- `load_ms` runs from navigation start to the moment the timer controls respond, measured with `performance.now()`.
- `referrer_type` is worked out in the browser from the referring domain.
- `current_streak_days` on `session_completed` includes the session that just finished.

## Session lifecycle

Every `session_started` ends in exactly one of these:

1. `session_completed`
2. `session_abandoned`, with reason `user_ended`, `page_closed` or `stale`
3. Nothing, if the student closes the tab and never returns. The warehouse treats a session with no end event 24 hours after its start as abandoned, with reason `no_end_event`.

A running session is saved to localStorage, so a reload or a crashed tab resumes it rather than starting a new one.

## Experiment exposure

- `experiment_exposed` fires when the screen that differs between arms renders, not when the flag is evaluated. A user who never reaches that screen isn't in the analysis.
- It fires once per user per experiment; the app remembers in localStorage. The analysis still uses each user's first exposure, in case a cleared cache sends it twice.
- The flag value is read once per page load and cached, so nobody switches arms partway through a session.
- PostHog also sends its own `$feature_flag_called` event. The warehouse uses ours, because it fires at the point of divergence.
- Users with Do Not Track or Global Privacy Control on never load PostHog, so they always get control and are never exposed.

## Privacy rules

These aren't preferences. Day 2 tests cover rules 1 to 3.

1. **No personal data and no free text.** No names, emails, phone numbers or anything the user typed. The session goal never leaves the device; events carry `goal_set: true`, never the goal. The only properties allowed are the ones in this file, with the types listed, and none of them is an open-ended text field.
2. **Anonymous IDs only.** The ID is the random one PostHog generates on the first visit, stored with `persistence: 'localStorage'`, so there are no cookies. The app never calls `identify()` and never sets person properties, so with `person_profiles: 'identified_only'` no person profiles are created.
3. **Respect Do Not Track and Global Privacy Control.** If `navigator.doNotTrack === '1'` or `navigator.globalPrivacyControl === true`, PostHog isn't loaded at all: no events and no feature-flag requests. The app works the same and shows the control experience. `respect_dnt: true` is set as well, as a backstop.
4. **No IP addresses.** "Discard client IP data" is turned on in the PostHog project settings. The old `ip: false` init option is deprecated and does nothing, so the project setting is the only real control.
5. **Nothing captured implicitly.** `autocapture: false` (autocapture can pick up text on the page), `capture_pageview: false` (`app_opened` replaces it), `disable_session_recording: true`, and `disable_external_dependency_loading: true`, so no surveys, heatmaps or site apps get loaded.
6. **No query strings.** A `before_send` hook strips query strings and fragments from `$current_url` and `$referrer`.
7. **An off switch.** The footer has a "Turn off analytics" toggle that calls `posthog.opt_out_capturing()` and remembers the choice.
8. **Exports stay local.** Event exports go into `data/`, which is gitignored. Synthetic events are never sent to PostHog; they exist only in the local DuckDB file, tagged `source = 'synthetic'`.

## Changing this plan

Change this file in the same commit as the code, bump the version at the top and add a changelog line. Because of the typed wrapper, the code won't build until the two agree.

### Changelog

- **v1, 2026-10-29**: first version, seven events.
