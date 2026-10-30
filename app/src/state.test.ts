import { beforeEach, describe, expect, it } from 'vitest'
import { freshState, loadState, saveState } from './state'

beforeEach(() => localStorage.clear())

describe('loadState', () => {
  it('starts fresh with nothing saved', () => {
    expect(loadState('k')).toEqual(freshState())
  })

  it('round-trips a saved state', () => {
    const state = { ...freshState(), sessionsCompleted: 3, history: { '2026-10-29': { sessions: 3, minutes: 75 } } }
    saveState('k', state)
    expect(loadState('k')).toEqual(state)
  })

  it('survives corrupt or hand-edited data', () => {
    localStorage.setItem('k', '{not json')
    expect(loadState('k')).toEqual(freshState())

    localStorage.setItem(
      'k',
      JSON.stringify({
        version: 1,
        sessionsStarted: -4,
        lastLength: 33,
        lastGoal: 'my secret plans',
        history: { 'not-a-date': { sessions: 1 }, '2026-10-29': { sessions: 2, minutes: 50 } },
        active: { id: 'x', plannedMinutes: 25 },
      }),
    )
    const state = loadState('k')
    expect(state.sessionsStarted).toBe(0)
    expect(state.lastLength).toBe(25)
    expect(state.lastGoal).toBeNull()
    expect(state.history).toEqual({ '2026-10-29': { sessions: 2, minutes: 50 } })
    expect(state.active).toBeNull()
  })
})
