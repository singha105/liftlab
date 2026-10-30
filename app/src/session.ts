import type { GoalId, SessionLength } from './config'

export interface ActiveSession {
  id: string
  plannedMinutes: SessionLength
  goal: GoalId | null
  startedAt: number
  pausedAt: number | null
  /** Total time spent in finished pauses. */
  pausedMs: number
  pauseCount: number
}

// All timing is derived from timestamps, so a throttled background tab, a sleeping laptop or
// a reload never makes the clock drift. `unitMs` is one timer minute (one second in demo mode).

function pausedSoFar(s: ActiveSession, now: number): number {
  return s.pausedMs + (s.pausedAt === null ? 0 : now - s.pausedAt)
}

/** Focus time so far, pauses excluded. */
export function focusedMs(s: ActiveSession, now: number): number {
  return Math.max(0, now - s.startedAt - pausedSoFar(s, now))
}

export function remainingMs(s: ActiveSession, now: number, unitMs: number): number {
  return Math.max(0, s.plannedMinutes * unitMs - focusedMs(s, now))
}

/** When the timer reaches (or reached) zero, if nobody pauses it again. */
export function endsAt(s: ActiveSession, now: number, unitMs: number): number {
  return s.startedAt + pausedSoFar(s, now) + s.plannedMinutes * unitMs
}
