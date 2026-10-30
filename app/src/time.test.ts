import { describe, expect, it } from 'vitest'
import { addDays, currentStreak, dayKey, longestStreak, weekStart, weekTotals, type History } from './time'

const done = (...days: string[]): History =>
  Object.fromEntries(days.map((d) => [d, { sessions: 1, minutes: 25 }]))

describe('dates', () => {
  it('formats local calendar dates', () => {
    expect(dayKey(new Date(2026, 0, 5, 23, 59))).toBe('2026-01-05')
  })

  it('adds days across months, years and DST changes', () => {
    expect(addDays('2026-01-31', 1)).toBe('2026-02-01')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDays('2026-03-08', 1)).toBe('2026-03-09')
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31')
  })

  it('finds the Monday of a week', () => {
    expect(weekStart('2026-10-29')).toBe('2026-10-26') // Thursday
    expect(weekStart('2026-10-26')).toBe('2026-10-26') // Monday
    expect(weekStart('2026-11-01')).toBe('2026-10-26') // Sunday
  })
})

describe('streaks', () => {
  it('counts back from today', () => {
    expect(currentStreak(done('2026-10-27', '2026-10-28', '2026-10-29'), '2026-10-29')).toBe(3)
  })

  it('stays alive until the end of today if yesterday counted', () => {
    expect(currentStreak(done('2026-10-27', '2026-10-28'), '2026-10-29')).toBe(2)
  })

  it('breaks after a missed day', () => {
    expect(currentStreak(done('2026-10-26', '2026-10-27'), '2026-10-29')).toBe(0)
    expect(currentStreak({}, '2026-10-29')).toBe(0)
  })

  it('finds the longest run', () => {
    const history = done('2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07')
    expect(longestStreak(history)).toBe(3)
    expect(longestStreak({})).toBe(0)
  })
})

describe('weekTotals', () => {
  it('sums one Monday-to-Sunday week only', () => {
    const history: History = {
      '2026-10-25': { sessions: 9, minutes: 225 }, // Sunday before
      '2026-10-26': { sessions: 2, minutes: 40 },
      '2026-11-01': { sessions: 1, minutes: 50 },
    }
    expect(weekTotals(history, '2026-10-26')).toEqual({
      sessions: 3,
      minutes: 90,
      perDay: [2, 0, 0, 0, 0, 0, 1],
    })
  })
})
