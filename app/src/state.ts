import { DEFAULT_LENGTH, GOALS, LENGTHS, type GoalId, type SessionLength } from './config'
import type { ActiveSession } from './session'
import { readJSON, writeJSON } from './storage'
import type { History } from './time'

export interface State {
  version: 1
  firstOpenAt: number | null
  sessionsStarted: number
  sessionsCompleted: number
  history: History
  /** Kept separately because old history gets pruned. */
  longestStreak: number
  active: ActiveSession | null
  lastLength: SessionLength
  lastGoal: GoalId | null
  /** Monday of the last week the summary opened for (or was skipped for). */
  summaryWeek: string | null
  /** This device's arm in each experiment it was exposed to, by experiment key. */
  experiments: Record<string, Arm>
}

export type Arm = 'control' | 'test'

export function freshState(): State {
  return {
    version: 1,
    firstOpenAt: null,
    sessionsStarted: 0,
    sessionsCompleted: 0,
    history: {},
    longestStreak: 0,
    active: null,
    lastLength: DEFAULT_LENGTH,
    lastGoal: null,
    summaryWeek: null,
    experiments: {},
  }
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)
const count = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : 0)
const isLength = (v: unknown): v is SessionLength => LENGTHS.some((l) => l === v)
const isGoal = (v: unknown): v is GoalId => GOALS.some((g) => g.id === v)
const isArm = (v: unknown): v is Arm => v === 'control' || v === 'test'

function readActive(v: unknown): ActiveSession | null {
  if (!isRecord(v) || typeof v.id !== 'string' || !isLength(v.plannedMinutes)) return null
  if (typeof v.startedAt !== 'number') return null
  return {
    id: v.id,
    plannedMinutes: v.plannedMinutes,
    goal: isGoal(v.goal) ? v.goal : null,
    startedAt: v.startedAt,
    pausedAt: typeof v.pausedAt === 'number' ? v.pausedAt : null,
    pausedMs: count(v.pausedMs),
    pauseCount: count(v.pauseCount),
  }
}

function readExperiments(v: unknown): Record<string, Arm> {
  const experiments: Record<string, Arm> = {}
  if (!isRecord(v)) return experiments
  for (const [key, arm] of Object.entries(v)) if (isArm(arm)) experiments[key] = arm
  return experiments
}

function readHistory(v: unknown): History {
  const history: History = {}
  if (!isRecord(v)) return history
  for (const [day, totals] of Object.entries(v)) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(day) && isRecord(totals) && count(totals.sessions) > 0) {
      history[day] = { sessions: count(totals.sessions), minutes: count(totals.minutes) }
    }
  }
  return history
}

/** Saved state is untrusted (hand edits, old versions, corruption): keep what parses, default the rest. */
export function loadState(key: string): State {
  const saved = readJSON(key)
  const state = freshState()
  if (!isRecord(saved) || saved.version !== 1) return state
  state.firstOpenAt = typeof saved.firstOpenAt === 'number' ? saved.firstOpenAt : null
  state.sessionsStarted = count(saved.sessionsStarted)
  state.sessionsCompleted = count(saved.sessionsCompleted)
  state.history = readHistory(saved.history)
  state.longestStreak = count(saved.longestStreak)
  state.active = readActive(saved.active)
  state.lastLength = isLength(saved.lastLength) ? saved.lastLength : DEFAULT_LENGTH
  state.lastGoal = isGoal(saved.lastGoal) ? saved.lastGoal : null
  state.summaryWeek = typeof saved.summaryWeek === 'string' ? saved.summaryWeek : null
  state.experiments = readExperiments(saved.experiments)
  return state
}

export function saveState(key: string, state: State): void {
  writeJSON(key, state)
}
