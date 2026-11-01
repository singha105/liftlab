# EXP-001: PostHog setup

Done by hand in the PostHog UI, in this order. The app code is already deployed: until the flag exists, every visitor sees control and nobody is exposed.

The pre-registration in [EXP-001.md](EXP-001.md) is the source of truth. If a PostHog setting can't match it, the warehouse analysis still decides, and PostHog's experiment page is a live monitor only.

## Before you start

These are still open from Day 2. Without them the live site sends nothing.

1. **Project.** PostHog Cloud, US region, project "StudySprint".
2. **IP addresses.** Project settings → turn on **Discard client IP data**.
3. **Project key in the build.** Copy the project API key (starts with `phc_`). In GitHub: singha105/liftlab → Settings → Secrets and variables → Actions → **Variables** tab → New repository variable, name `VITE_POSTHOG_KEY`, value the key. (Or tell me and I'll run `gh variable set VITE_POSTHOG_KEY` after you OK it.) Then Actions → Deploy app → Run workflow on `main`.
4. **Check it's live.** Open https://singha105.github.io/liftlab/?demo=1 in a private window, wait a few seconds, then look in PostHog under Activity for an `app_opened` event. Demo mode marks every event `is_demo`, so the check doesn't add a fake user to the real numbers. The page footer should say "Usage events go to PostHog". New event names can take a few minutes to show in Activity; Data management → Event definitions lists them sooner.

## Create the experiment

Experiments → **New experiment**. The wizard has three steps.

PostHog's event pickers only offer events the project has already received. Steps 1 and 2 work on an empty project; step 3 needs the live site to have sent `app_opened` and the session events first. A demo sprint (`?demo=1`, finished once and abandoned once) sends them, marked `is_demo`. On a new project, PostHog first asks which products you want: pick Product Analytics, Feature Flags and Experiments only (no Session Replay), and skip the SDK install.

### Step 1: Description

- **Name:** `EXP-001 Quick Start`
- **Hypothesis:** paste the hypothesis from EXP-001.md.
- **Feature flag key:** change the generated key to exactly **`exp-001`**. The app reads this key and nothing else.

### Step 2: Variant rollout

- **Variants:** leave the defaults, `control` and `test`, with the names exactly as written.
- **Split:** 50 / 50.
- **Rollout percentage:** 100%.
- **Participant type:** users.
- **No release conditions.** "New users only" is enforced by the app, which reads the flag only on a device's first open. PostHog can't target new users itself: StudySprint never creates person profiles (`person_profiles: 'identified_only'` and no `identify()`), so there are no person properties to filter on. A person-property condition would quietly match nobody or everybody.

### Step 3: Analytics

**Inclusion criteria**

- **Exposure event:** choose **Custom event**, then select `experiment_exposed`.
- Add two property filters on that event: `experiment_key` equals `exp-001`, and `is_demo` equals `false`.
- PostHog won't have seen `experiment_exposed` before launch: the flag stays disabled while the experiment is a draft, so nobody is enrolled. Register the name first under Data management → Event definitions → **Create event** (exactly `experiment_exposed`; names can't be changed later). In the property filter, switch the category to **Event properties** and choose "show properties that haven't been seen with this event" to find `experiment_key` and `is_demo`, then type the values (`exp-001`, `false`).
- **Multiple variant handling:** **Exclude from analysis**, the default.
- **Filter test accounts:** on (the default). The project's filter only drops people marked `$internal_or_test_user`, which anonymous StudySprint visitors never are, so it removes nobody.

The app puts `$feature/exp-001` on `experiment_exposed`, which is how PostHog knows each user's arm. Nothing else needs it.

**Primary metric**

- **+ Add primary metric** → type **Funnel**.
- Step: `session_completed`. The exposure is step one automatically.
- **Conversion window:** **24 hours**.
- Name it `Activation (24 h)`.

This matches the pre-registered definition to within seconds: PostHog starts the 24 hours at exposure, the warehouse at the first `app_opened`, and exposure follows the first open almost immediately.

**Secondary metric**

- **+ Add secondary metric** → type **Mean**, event `session_completed`, aggregation **count**, conversion window **7 days**.
- Name it `Completed sessions per user (7 d)`.

**Guardrails** (also added as secondary metrics)

- **Abandon rate:** type **Ratio**. Numerator: `session_abandoned`, count. Denominator: `session_started`, count. Conversion window 7 days. PostHog can't see sessions that never send an end event, so its number runs a little low. The warehouse version, which counts those after 24 hours, is the one the decision rule uses.
- **Page load:** PostHog has no p75 aggregation, so this guardrail lives only in the warehouse (`load_ms` on `app_opened` after exposure). Don't add it here.

Click **Save as draft**. Leave Replay Vision off. Saving creates the `exp-001` flag in a disabled state; launching turns it on.

## Before launching

1. On the experiment's **Settings** tab, edit **Statistics** and choose **Frequentist** with a **95%** confidence level, sequential testing off (the team default). The pre-registration reads the primary once with a two-sided z-test at alpha 0.05, so PostHog's default Bayesian view would answer a different question. Leave CUPED disabled: new users have no pre-period.
2. Open the linked feature flag and check: key `exp-001`, variants `control` and `test` at 50% each, rollout 100%, no conditions.
3. Click **Launch**. Write the launch date into the Day log in PROGRESS.md: the 8-week limit counts from here.

## After launching

- **Smoke test.** In a fresh private window, open the live site and wait two seconds. You'll see either the normal start screen (control) or a single "Start a 25-minute focus" button (test). In Activity, check for exactly one `experiment_exposed` from that visitor, with `experiment_key: exp-001`, a `variant`, and `$feature/exp-001` agreeing with it. Then reload: there should be no second exposure.
- **Preview without counting.** `https://singha105.github.io/liftlab/?demo=1&variant=test` shows the test screen in demo mode. It never enrolls you and sends no exposure. Use a private window: Quick Start only shows before a first session, so a browser that has already run a demo sprint shows the normal screen.
- **Weekly checks.** Only the SRM and the guardrails, as pre-registered. Don't read the primary metric until 1,377 users per arm or the 8-week limit.
- **Don't edit the experiment after launch.** Changing the split, the variants or the metrics after launch breaks the pre-registration. If something has to change, stop the experiment, add an amendment to EXP-001.md, and relaunch with fresh assignment.
- **Ending it.** At 1,377 per arm or 8 weeks, stop the experiment in PostHog, export the events (`uv run liftlab export-posthog`), and run the analysis on the warehouse. Don't use PostHog's "Ship variant" button until the decision rule says SHIP.
