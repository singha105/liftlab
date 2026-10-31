import { beforeEach, describe, expect, it, vi } from 'vitest'
import page from '../index.html?raw'
import type { SuperProps, Variant } from './analytics'
import { freshState, type State } from './state'

const spy = vi.hoisted(() => ({
  getVariant: vi.fn(),
  init: vi.fn(),
  context: vi.fn(),
  exposed: vi.fn(),
  started: vi.fn(),
}))
vi.mock('./analytics', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./analytics')>()
  return {
    ...actual,
    getVariant: spy.getVariant,
    initAnalytics: (props: SuperProps) => {
      spy.init(props)
      return actual.initAnalytics(props)
    },
    setExperimentContext: spy.context,
    trackExperimentExposed: spy.exposed,
    trackSessionStarted: spy.started,
  }
})

/** Renders index.html and runs a fresh copy of the app on it, as a page load would. */
async function openApp(): Promise<void> {
  document.body.innerHTML = new DOMParser().parseFromString(page, 'text/html').body.innerHTML
  vi.resetModules()
  const { startApp } = await import('./app')
  startApp()
}

const settle = () => new Promise((resolve) => setTimeout(resolve))
const visible = (id: string) => document.getElementById(id)?.hidden === false
const click = (id: string) => document.getElementById(id)?.click()
const saved = (): State => JSON.parse(localStorage.getItem('studysprint') ?? '{}')

function returning(changes: Partial<State>): void {
  const state = { ...freshState(), firstOpenAt: Date.now() - 3_600_000, ...changes }
  localStorage.setItem('studysprint', JSON.stringify(state))
}

beforeEach(() => {
  vi.clearAllMocks()
  spy.getVariant.mockResolvedValue(null)
  localStorage.clear()
  history.replaceState(null, '', '/')
})

describe('start screen', () => {
  // The snapshot was recorded from the app before EXP-001's code existed. Control has to keep
  // matching it byte for byte.
  it('is unchanged for a first-time visitor outside the experiment', async () => {
    await openApp()
    await settle()
    await expect(document.body.innerHTML).toMatchFileSnapshot('__snapshots__/start-screen.html')
    // innerHTML doesn't show which radio is checked.
    expect(document.querySelector<HTMLInputElement>('input[name=length]:checked')?.value).toBe('25')
    expect(spy.exposed).not.toHaveBeenCalled()
  })
})

describe('EXP-001 exposure', () => {
  it('exposes control once and leaves the start screen exactly as it was', async () => {
    spy.getVariant.mockResolvedValue('control')
    await openApp()
    await settle()
    expect(spy.getVariant).toHaveBeenCalledWith('exp-001')
    expect(spy.exposed).toHaveBeenCalledTimes(1)
    expect(spy.exposed).toHaveBeenCalledWith({ experiment_key: 'exp-001', variant: 'control' })
    expect(spy.context).toHaveBeenCalledWith('exp-001', 'control')
    expect(saved().experiments).toEqual({ 'exp-001': 'control' })
    await expect(document.body.innerHTML).toMatchFileSnapshot('__snapshots__/start-screen.html')
  })

  it('switches the test arm to Quick Start at the moment of exposure', async () => {
    let resolveFlag: (variant: Variant) => void = () => undefined
    spy.getVariant.mockReturnValue(new Promise((resolve) => (resolveFlag = resolve)))
    await openApp()
    expect(visible('screen-setup')).toBe(true)
    expect(spy.exposed).not.toHaveBeenCalled()
    resolveFlag('test')
    await settle()
    expect(visible('screen-quick')).toBe(true)
    expect(visible('screen-setup')).toBe(false)
    expect(document.getElementById('quick-start')?.textContent).toBe('Start a 25-minute focus')
    expect(spy.exposed).toHaveBeenCalledTimes(1)
    expect(spy.exposed).toHaveBeenCalledWith({ experiment_key: 'exp-001', variant: 'test' })
    expect(saved().experiments).toEqual({ 'exp-001': 'test' })
  })

  it('leaves out a visitor who touched the start screen before the flag loaded', async () => {
    let resolveFlag: (variant: Variant) => void = () => undefined
    spy.getVariant.mockReturnValue(new Promise((resolve) => (resolveFlag = resolve)))
    await openApp()
    const fifty = document.querySelector<HTMLInputElement>('input[name=length][value="50"]')
    fifty?.click()
    resolveFlag('test')
    await settle()
    expect(spy.exposed).not.toHaveBeenCalled()
    expect(document.getElementById('screen-quick')).toBeNull()
    expect(saved().experiments).toEqual({})
  })

  it('never enrolls a returning visitor', async () => {
    returning({})
    spy.getVariant.mockResolvedValue('test')
    await openApp()
    await settle()
    expect(spy.getVariant).not.toHaveBeenCalled()
    expect(spy.exposed).not.toHaveBeenCalled()
    expect(visible('screen-setup')).toBe(true)
  })

  it('never enrolls demo mode, which can preview an arm instead', async () => {
    history.replaceState(null, '', '/?demo=1&variant=test')
    await openApp()
    await settle()
    expect(spy.getVariant).not.toHaveBeenCalled()
    expect(spy.exposed).not.toHaveBeenCalled()
    expect(visible('screen-quick')).toBe(true)
    expect(spy.init).toHaveBeenCalledWith(expect.objectContaining({ experiment_key: 'none' }))
  })
})

describe('Quick Start', () => {
  it('starts a 25-minute session with no goal in one click', async () => {
    spy.getVariant.mockResolvedValue('test')
    await openApp()
    await settle()
    click('quick-start')
    expect(spy.started).toHaveBeenCalledWith(
      expect.objectContaining({
        planned_minutes: 25,
        goal_set: false,
        start_method: 'quick_start',
        session_number: 1,
      }),
    )
    expect(visible('screen-timer')).toBe(true)
  })

  it('opens the normal start screen from Customize', async () => {
    spy.getVariant.mockResolvedValue('test')
    await openApp()
    await settle()
    click('customize')
    expect(visible('screen-setup')).toBe(true)
    expect(visible('screen-quick')).toBe(false)
    click('start')
    expect(spy.started).toHaveBeenCalledWith(expect.objectContaining({ start_method: 'preset' }))
  })

  it('stays on later visits until the first session, without asking PostHog again', async () => {
    returning({ experiments: { 'exp-001': 'test' } })
    await openApp()
    expect(visible('screen-quick')).toBe(true)
    expect(spy.getVariant).not.toHaveBeenCalled()
    expect(spy.init).toHaveBeenCalledWith(
      expect.objectContaining({ experiment_key: 'exp-001', variant: 'test' }),
    )
  })

  it('gives way to the normal screen once a session has started', async () => {
    returning({ experiments: { 'exp-001': 'test' }, sessionsStarted: 1 })
    await openApp()
    expect(visible('screen-setup')).toBe(true)
    expect(document.getElementById('screen-quick')).toBeNull()
  })
})
