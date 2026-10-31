import type { CaptureResult, PostHog, PostHogConfig, Properties } from 'posthog-js'
import { readJSON, writeJSON } from './storage'

/**
 * The tracking plan (docs/TRACKING_PLAN.md) as data. Event and property types are derived
 * from it, and a test compares it with the markdown, so the two can't drift apart.
 */
export const PLAN = {
  app_opened: {
    is_first_open: 'bool',
    load_ms: 'int',
    referrer_type: ['direct', 'search', 'social', 'other'],
    current_streak_days: 'int',
  },
  session_started: {
    session_id: 'uuid',
    planned_minutes: [15, 25, 50],
    goal_set: 'bool',
    start_method: ['preset', 'quick_start'],
    session_number: 'int',
  },
  session_completed: {
    session_id: 'uuid',
    planned_minutes: [15, 25, 50],
    actual_minutes: 'int',
    pause_count: 'int',
    goal_set: 'bool',
    current_streak_days: 'int',
    is_first_completion: 'bool',
    completed_while_away: 'bool',
  },
  session_abandoned: {
    session_id: 'uuid',
    planned_minutes: [15, 25, 50],
    elapsed_seconds: 'int',
    pause_count: 'int',
    goal_set: 'bool',
    reason: ['user_ended', 'page_closed', 'stale'],
  },
  streak_viewed: {
    current_streak_days: 'int',
    longest_streak_days: 'int',
    surface: ['completion_screen', 'home'],
  },
  weekly_summary_viewed: {
    sessions_completed_week: 'int',
    focus_minutes_week: 'int',
    opened_by: ['new_week', 'user'],
  },
  experiment_exposed: {
    experiment_key: 'string',
    variant: ['control', 'test'],
  },
} as const

/** Registered once and sent with every event. */
export const SUPER_PROPERTIES = {
  app_version: 'string',
  experiment_key: 'string',
  variant: ['control', 'test', 'none'],
  is_demo: 'bool',
} as const

type Value<S> = S extends 'bool'
  ? boolean
  : S extends 'int'
    ? number
    : S extends 'uuid' | 'string'
      ? string
      : S extends readonly (infer V)[]
        ? V
        : never
type Props<Spec> = { -readonly [K in keyof Spec]: Value<Spec[K]> }

export type EventName = keyof typeof PLAN
export type EventProps<E extends EventName> = Props<(typeof PLAN)[E]>
export type SuperProps = Props<typeof SUPER_PROPERTIES>
export type Variant = EventProps<'experiment_exposed'>['variant']
export type ReferrerType = EventProps<'app_opened'>['referrer_type']
export type AnalyticsStatus = 'on' | 'no_key' | 'dnt' | 'opted_out'

// Everything PostHog could collect on its own is switched off; the only events sent are
// the ones in PLAN, and beforeSend drops anything else that slips through.
export const PRIVACY_CONFIG = {
  persistence: 'localStorage',
  person_profiles: 'identified_only',
  autocapture: false,
  capture_pageview: false,
  capture_pageleave: false,
  capture_performance: false,
  capture_dead_clicks: false,
  capture_exceptions: false,
  capture_heatmaps: false,
  rageclick: false,
  disable_session_recording: true,
  disable_surveys: true,
  disable_web_experiments: true,
  disable_product_tours: true,
  disable_conversations: true,
  disable_external_dependency_loading: true,
  respect_dnt: true,
  save_referrer: false,
} satisfies Partial<PostHogConfig>

const OPT_OUT_KEY = 'studysprint:analytics-off'
const DEFAULT_HOST = 'https://us.i.posthog.com'
const PLANNED_EVENTS = new Set<string>(Object.keys(PLAN))
// PostHog's timezone fields are coarse location, which the plan doesn't collect.
const DROPPED_PROPERTIES = ['$timezone', '$timezone_offset'] as const

let status: AnalyticsStatus = 'no_key'
let client: PostHog | null = null
let loading: Promise<PostHog | null> | null = null
let superProps: SuperProps | null = null
let pending: { event: EventName; properties: Properties; at: Date }[] = []

type PrivacyNavigator = { doNotTrack?: string | null; globalPrivacyControl?: boolean }

export function privacySignalOn(nav: PrivacyNavigator = navigator): boolean {
  return nav.doNotTrack === '1' || nav.globalPrivacyControl === true
}

export function analyticsStatus(): AnalyticsStatus {
  return status
}

/**
 * Loads PostHog after first render (it's a separate chunk), and only when there's a key and
 * the visitor hasn't asked not to be tracked. Events tracked before it loads are queued.
 */
export function initAnalytics(props: SuperProps): AnalyticsStatus {
  superProps = props
  const key = import.meta.env.VITE_POSTHOG_KEY
  if (!key) return (status = 'no_key')
  if (privacySignalOn()) return (status = 'dnt')
  if (readJSON(OPT_OUT_KEY) === true) return (status = 'opted_out')

  status = 'on'
  loading ??= import('posthog-js')
    .then(({ default: posthog }) => {
      posthog.init(key, {
        api_host: import.meta.env.VITE_POSTHOG_HOST || DEFAULT_HOST,
        ...PRIVACY_CONFIG,
        before_send: beforeSend,
      })
      // Our own opt-out flag is the source of truth; clear any stale PostHog opt-out.
      if (posthog.has_opted_out_capturing()) posthog.opt_in_capturing()
      if (superProps) posthog.register(superProps)
      for (const e of pending) posthog.capture(e.event, e.properties, { timestamp: e.at })
      pending = []
      client = posthog
      return posthog
    })
    .catch(() => {
      // Blocked by an ad blocker or offline: carry on without analytics.
      pending = []
      return null
    })
  return status
}

export function beforeSend(event: CaptureResult | null): CaptureResult | null {
  if (!event || !PLANNED_EVENTS.has(event.event)) return null
  for (const [key, value] of Object.entries(event.properties)) {
    if (key.startsWith('$') && typeof value === 'string' && /^https?:\/\//.test(value)) {
      event.properties[key] = stripQuery(value)
    }
  }
  for (const key of DROPPED_PROPERTIES) delete event.properties[key]
  delete event.$set
  delete event.$set_once
  return event
}

export function stripQuery(url: string): string {
  try {
    const u = new URL(url)
    u.search = ''
    u.hash = ''
    return u.toString()
  } catch {
    return url.split(/[?#]/)[0] ?? ''
  }
}

/** Turning analytics off is remembered, and later visits don't load PostHog at all. */
export function setAnalyticsEnabled(enabled: boolean): AnalyticsStatus {
  writeJSON(OPT_OUT_KEY, !enabled)
  if (!enabled) {
    client?.opt_out_capturing()
    pending = []
    status = 'opted_out'
  } else if (client) {
    client.opt_in_capturing()
    status = 'on'
  } else if (superProps) {
    initAnalytics(superProps)
  }
  return status
}

function capture<E extends EventName>(event: E, props: EventProps<E>, at = new Date()): void {
  if (status !== 'on') return
  const properties: Properties = { ...props }
  if (client) client.capture(event, properties, { timestamp: at })
  else pending.push({ event, properties, at })
}

export const trackAppOpened = (p: EventProps<'app_opened'>) => capture('app_opened', p)
export const trackSessionStarted = (p: EventProps<'session_started'>) =>
  capture('session_started', p)
/** `at` is when the timer reached zero, which can be earlier than now (background tab, away check). */
export const trackSessionCompleted = (p: EventProps<'session_completed'>, at?: Date) =>
  capture('session_completed', p, at)
export const trackSessionAbandoned = (p: EventProps<'session_abandoned'>) =>
  capture('session_abandoned', p)
export const trackStreakViewed = (p: EventProps<'streak_viewed'>) => capture('streak_viewed', p)
export const trackWeeklySummaryViewed = (p: EventProps<'weekly_summary_viewed'>) =>
  capture('weekly_summary_viewed', p)
export const trackExperimentExposed = (p: EventProps<'experiment_exposed'>) =>
  capture('experiment_exposed', p)

/**
 * This user's arm of a feature-flag experiment, or null if they aren't in it: no key, Do Not
 * Track, opted out, blocked, a slow network, or a flag that isn't control or test. The app
 * shows control to anyone without an arm, but only users with one are exposed, so a slow
 * network can't quietly add people to the control arm.
 */
export function getVariant(flagKey: string, timeoutMs = 1500): Promise<Variant | null> {
  return new Promise((resolve) => {
    let settled = false
    const settle = (variant: Variant | null) => {
      if (!settled) {
        settled = true
        resolve(variant)
      }
    }
    setTimeout(() => settle(null), timeoutMs)
    if (!loading) return settle(null)
    void loading.then((posthog) => {
      if (!posthog) return settle(null)
      posthog.onFeatureFlags(() => {
        const value = posthog.getFeatureFlag(flagKey, { send_event: false })
        settle(value === 'control' || value === 'test' ? value : null)
      })
    })
  })
}

/** Tags every later event with the experiment and arm this user is in. */
export function setExperimentContext(experiment_key: string, variant: Variant): void {
  if (superProps) superProps = { ...superProps, experiment_key, variant }
  client?.register({ experiment_key, variant })
}

const SEARCH_DOMAINS = ['google.', 'bing.com', 'duckduckgo.com', 'search.yahoo.com', 'ecosia.org', 'baidu.com', 'yandex.', 'search.brave.com']
const SOCIAL_DOMAINS = ['t.co', 'x.com', 'twitter.com', 'facebook.com', 'instagram.com', 'linkedin.com', 'lnkd.in', 'reddit.com', 'youtube.com', 'tiktok.com', 'discord.com', 'threads.net', 'whatsapp.com']

function matchesDomain(host: string, domain: string): boolean {
  if (domain.endsWith('.')) return host.startsWith(domain) || host.includes(`.${domain}`)
  return host === domain || host.endsWith(`.${domain}`)
}

/** Coarse traffic source, worked out in the browser so no referrer URL needs to be kept. */
export function referrerType(referrer: string, ownHost: string): ReferrerType {
  if (!referrer) return 'direct'
  let host: string
  try {
    host = new URL(referrer).hostname
  } catch {
    return 'other'
  }
  if (host === ownHost) return 'direct'
  if (SEARCH_DOMAINS.some((d) => matchesDomain(host, d))) return 'search'
  if (SOCIAL_DOMAINS.some((d) => matchesDomain(host, d))) return 'social'
  return 'other'
}
