import { describe, expect, it } from 'vitest'
import { endsAt, focusedMs, remainingMs, type ActiveSession } from './session'

const MIN = 60_000
const session = (over: Partial<ActiveSession> = {}): ActiveSession => ({
  id: 's1',
  plannedMinutes: 25,
  goal: null,
  startedAt: 0,
  pausedAt: null,
  pausedMs: 0,
  pauseCount: 0,
  ...over,
})

describe('session timing', () => {
  it('counts down from the planned length', () => {
    expect(remainingMs(session(), 10 * MIN, MIN)).toBe(15 * MIN)
    expect(endsAt(session(), 10 * MIN, MIN)).toBe(25 * MIN)
  })

  it('leaves finished and ongoing pauses out of focus time', () => {
    const s = session({ pausedMs: 5 * MIN, pausedAt: 20 * MIN })
    expect(focusedMs(s, 22 * MIN)).toBe(15 * MIN)
    expect(endsAt(s, 22 * MIN, MIN)).toBe(32 * MIN)
  })

  it('never goes below zero', () => {
    expect(remainingMs(session(), 90 * MIN, MIN)).toBe(0)
  })

  it('scales to seconds in demo mode', () => {
    expect(remainingMs(session(), 10_000, 1000)).toBe(15_000)
  })
})
