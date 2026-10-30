import type { CaptureResult } from 'posthog-js'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import planDoc from '../../docs/TRACKING_PLAN.md?raw'
import * as analytics from './analytics'
import { PLAN, SUPER_PROPERTIES, beforeSend, referrerType, stripQuery } from './analytics'

const posthog = vi.hoisted(() => ({
  init: vi.fn(),
  register: vi.fn(),
  capture: vi.fn(),
  has_opted_out_capturing: vi.fn(() => false),
  opt_in_capturing: vi.fn(),
  opt_out_capturing: vi.fn(),
  onFeatureFlags: vi.fn(),
  getFeatureFlag: vi.fn(),
}))
vi.mock('posthog-js', () => ({ default: posthog }))

const SUPER = { app_version: 'abc1234', experiment_key: 'none', variant: 'none', is_demo: false } as const
const APP_OPENED = { is_first_open: true, load_ms: 120, referrer_type: 'direct', current_streak_days: 0 } as const

/** A fresh copy of the module, so each test starts with PostHog unloaded. */
async function freshAnalytics() {
  vi.resetModules()
  return import('./analytics')
}

async function settle() {
  await vi.dynamicImportSettled()
  await new Promise((resolve) => setTimeout(resolve))
}

function setPrivacySignals(values: { doNotTrack?: string; globalPrivacyControl?: boolean }) {
  for (const key of ['doNotTrack', 'globalPrivacyControl'] as const) {
    Object.defineProperty(navigator, key, { value: values[key], configurable: true })
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.stubEnv('VITE_POSTHOG_KEY', 'phc_test')
  vi.stubEnv('VITE_POSTHOG_HOST', 'https://us.i.posthog.com')
  setPrivacySignals({})
})

afterEach(() => vi.unstubAllEnvs())

describe('tracking plan', () => {
  const section = (title: string) => {
    const start = planDoc.indexOf(`\n## ${title}\n`)
    expect(start, `section "${title}"`).toBeGreaterThan(-1)
    const end = planDoc.indexOf('\n## ', start + 1)
    return planDoc.slice(start, end === -1 ? undefined : end)
  }
  const asText = (spec: unknown) => (Array.isArray(spec) ? `enum(${spec.join(', ')})` : String(spec))
  const asDoc = (props: object) =>
    Object.fromEntries(Object.entries(props).map(([name, spec]) => [name, asText(spec)]))

  it('has exactly the events and properties in docs/TRACKING_PLAN.md', () => {
    const documented: Record<string, Record<string, string>> = {}
    for (const line of section('Events').split('\n')) {
      const row = line.match(/^\| `([a-z_]+)` \|[^|]*\|([^|]*)\|/)
      if (!row?.[1] || !row[2]) continue
      documented[row[1]] = Object.fromEntries(
        [...row[2].matchAll(/`([a-z_]+):([^`]+)`/g)].map((m) => [m[1], m[2]]),
      )
    }
    const coded = Object.fromEntries(Object.entries(PLAN).map(([event, props]) => [event, asDoc(props)]))
    expect(coded).toEqual(documented)
  })

  it('has the super properties in docs/TRACKING_PLAN.md', () => {
    const documented: Record<string, string> = {}
    for (const line of section('Properties on every event').split('\n')) {
      const row = line.match(/^\| `([a-z_]+)` \| ([^|]+?) \|/)
      if (row?.[1] && row[2]) documented[row[1]] = row[2]
    }
    expect(asDoc(SUPER_PROPERTIES)).toEqual(documented)
  })

  it('has no open-ended text properties (privacy rule 1)', () => {
    const textProps = [...Object.values(PLAN), SUPER_PROPERTIES].flatMap((props) =>
      Object.entries(props)
        .filter(([, spec]) => spec === 'string' || spec === 'uuid')
        .map(([name]) => name),
    )
    expect(new Set(textProps)).toEqual(new Set(['session_id', 'experiment_key', 'app_version']))
  })

  it('rejects unplanned events and properties at compile time', () => {
    const typeChecks = () => {
      // @ts-expect-error misspelled property
      analytics.trackSessionCompleted({ session_id: 'x', planned_minutes: 25, actual_minute: 25, pause_count: 0, goal_set: false, current_streak_days: 1, is_first_completion: true, completed_while_away: false })
      // @ts-expect-error 30 isn't a preset length
      analytics.trackSessionStarted({ session_id: 'x', planned_minutes: 30, goal_set: false, start_method: 'preset', session_number: 1 })
      // @ts-expect-error free text isn't a planned property
      analytics.trackSessionStarted({ session_id: 'x', planned_minutes: 25, goal_set: true, goal: 'chapter 4', start_method: 'preset', session_number: 1 })
      // @ts-expect-error no such event
      analytics.trackSessionStart({})
    }
    expect(typeChecks).toBeTypeOf('function')
  })
})

describe('privacy', () => {
  const sources = import.meta.glob(['./*.ts', '!./*.test.ts'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>

  it('never identifies users or sets person properties (privacy rule 2)', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(4)
    for (const [file, code] of Object.entries(sources)) {
      expect(code, file).not.toMatch(/\.(identify|alias|setPersonProperties)\(/)
    }
  })

  it('initializes PostHog anonymous-only with everything automatic switched off', async () => {
    const a = await freshAnalytics()
    expect(a.initAnalytics(SUPER)).toBe('on')
    await settle()
    expect(posthog.init).toHaveBeenCalledOnce()
    const [key, config] = posthog.init.mock.calls[0] ?? []
    expect(key).toBe('phc_test')
    expect(config).toMatchObject({
      api_host: 'https://us.i.posthog.com',
      persistence: 'localStorage',
      person_profiles: 'identified_only',
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      capture_heatmaps: false,
      capture_exceptions: false,
      disable_session_recording: true,
      disable_surveys: true,
      respect_dnt: true,
      before_send: a.beforeSend,
    })
    expect(posthog.register).toHaveBeenCalledWith(SUPER)
  })

  it.each([
    ['Do Not Track', { doNotTrack: '1' }],
    ['Global Privacy Control', { globalPrivacyControl: true }],
  ])('never loads PostHog when %s is on (privacy rule 3)', async (_, signal) => {
    setPrivacySignals(signal)
    const a = await freshAnalytics()
    expect(a.initAnalytics(SUPER)).toBe('dnt')
    a.trackAppOpened(APP_OPENED)
    await settle()
    expect(posthog.init).not.toHaveBeenCalled()
    expect(posthog.capture).not.toHaveBeenCalled()
  })

  it('does nothing without a key (local dev)', async () => {
    vi.stubEnv('VITE_POSTHOG_KEY', '')
    const a = await freshAnalytics()
    expect(a.initAnalytics(SUPER)).toBe('no_key')
    a.trackAppOpened(APP_OPENED)
    await settle()
    expect(posthog.init).not.toHaveBeenCalled()
  })

  it('stops on opt-out and stays off on later visits (privacy rule 7)', async () => {
    const a = await freshAnalytics()
    a.initAnalytics(SUPER)
    await settle()
    expect(a.setAnalyticsEnabled(false)).toBe('opted_out')
    expect(posthog.opt_out_capturing).toHaveBeenCalled()
    a.trackAppOpened(APP_OPENED)
    expect(posthog.capture).not.toHaveBeenCalled()

    posthog.init.mockClear()
    const nextVisit = await freshAnalytics()
    expect(nextVisit.initAnalytics(SUPER)).toBe('opted_out')
    await settle()
    expect(posthog.init).not.toHaveBeenCalled()
  })
})

describe('capture', () => {
  it('queues events until PostHog loads, then sends them with their original time', async () => {
    const a = await freshAnalytics()
    a.initAnalytics(SUPER)
    a.trackAppOpened(APP_OPENED)
    expect(posthog.capture).not.toHaveBeenCalled()
    await settle()
    expect(posthog.capture).toHaveBeenCalledWith('app_opened', APP_OPENED, { timestamp: expect.any(Date) })
  })

  const event = (name: string, properties: Record<string, unknown> = {}) =>
    ({ uuid: 'u', event: name, properties: { ...properties } }) as CaptureResult

  it.each(['$pageview', '$pageleave', '$autocapture', '$rageclick', '$feature_flag_called', '$exception', '$web_vitals', '$opt_in', 'made_up_event'])(
    'drops %s before it leaves the browser',
    (name) => {
      expect(beforeSend(event(name))).toBeNull()
    },
  )

  it('keeps planned events but strips query strings, timezone and person properties', () => {
    const result = beforeSend({
      ...event('session_completed', {
        $current_url: 'https://singha105.github.io/liftlab/?demo=1#x',
        $referrer: 'https://www.google.com/search?q=study+timer',
        $session_entry_url: 'https://singha105.github.io/liftlab/?utm_source=x',
        $timezone: 'America/New_York',
        $timezone_offset: 240,
        planned_minutes: 25,
      }),
      $set_once: { $initial_referrer: 'https://example.com/?utm=1' },
    })
    expect(result?.properties).toEqual({
      $current_url: 'https://singha105.github.io/liftlab/',
      $referrer: 'https://www.google.com/search',
      $session_entry_url: 'https://singha105.github.io/liftlab/',
      planned_minutes: 25,
    })
    expect(result?.$set_once).toBeUndefined()
    expect(stripQuery('$direct')).toBe('$direct')
  })
})

describe('getVariant', () => {
  it('is control when PostHog is not running', async () => {
    vi.stubEnv('VITE_POSTHOG_KEY', '')
    const a = await freshAnalytics()
    a.initAnalytics(SUPER)
    await expect(a.getVariant('quick-start')).resolves.toBe('control')
  })

  it('reads the flag without sending $feature_flag_called', async () => {
    posthog.onFeatureFlags.mockImplementation((callback: () => void) => callback())
    posthog.getFeatureFlag.mockReturnValue('test')
    const a = await freshAnalytics()
    a.initAnalytics(SUPER)
    await expect(a.getVariant('quick-start')).resolves.toBe('test')
    expect(posthog.getFeatureFlag).toHaveBeenCalledWith('quick-start', { send_event: false })
  })

  it('falls back to control when flags are slow', async () => {
    posthog.onFeatureFlags.mockImplementation(() => () => undefined)
    const a = await freshAnalytics()
    a.initAnalytics(SUPER)
    await expect(a.getVariant('quick-start', 20)).resolves.toBe('control')
  })
})

describe('referrerType', () => {
  it.each([
    ['', 'direct'],
    ['https://singha105.github.io/liftlab/', 'direct'],
    ['https://www.google.co.uk/', 'search'],
    ['https://duckduckgo.com/', 'search'],
    ['https://t.co/abc', 'social'],
    ['https://old.reddit.com/r/GetStudying', 'social'],
    ['https://news.ycombinator.com/', 'other'],
    ['not a url', 'other'],
  ])('%s → %s', (referrer, expected) => {
    expect(referrerType(referrer, 'singha105.github.io')).toBe(expected)
  })
})
