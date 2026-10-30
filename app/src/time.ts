export const DAY_MS = 86_400_000

export interface DayTotals {
  sessions: number
  minutes: number
}

/** Completed sessions per local calendar day, keyed YYYY-MM-DD. */
export type History = Record<string, DayTotals>

const pad = (n: number) => String(n).padStart(2, '0')

/** Local calendar date as YYYY-MM-DD. Streaks follow the student's own clock, not UTC. */
export function dayKey(t: number | Date): string {
  const d = new Date(t)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function parseKey(key: string): Date {
  const [y = 1970, m = 1, d = 1] = key.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function addDays(key: string, days: number): string {
  const d = parseKey(key)
  d.setDate(d.getDate() + days)
  return dayKey(d)
}

/** The Monday of the week containing `key`. */
export function weekStart(key: string): string {
  return addDays(key, -((parseKey(key).getDay() + 6) % 7))
}

/** Days in a row with a completed session, ending today, or yesterday if today has none yet. */
export function currentStreak(history: History, today: string): number {
  let day = history[today] ? today : addDays(today, -1)
  let streak = 0
  while (history[day]) {
    streak++
    day = addDays(day, -1)
  }
  return streak
}

export function longestStreak(history: History): number {
  let best = 0
  let run = 0
  let prev = ''
  for (const day of Object.keys(history).sort()) {
    run = prev && addDays(prev, 1) === day ? run + 1 : 1
    best = Math.max(best, run)
    prev = day
  }
  return best
}

export function weekTotals(history: History, monday: string): DayTotals & { perDay: number[] } {
  const days = Array.from({ length: 7 }, (_, i) => history[addDays(monday, i)])
  return {
    sessions: days.reduce((sum, d) => sum + (d?.sessions ?? 0), 0),
    minutes: days.reduce((sum, d) => sum + (d?.minutes ?? 0), 0),
    perDay: days.map((d) => d?.sessions ?? 0),
  }
}
