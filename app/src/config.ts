export const LENGTHS = [15, 25, 50] as const
export type SessionLength = (typeof LENGTHS)[number]
export const DEFAULT_LENGTH: SessionLength = 25

export const GOALS = [
  { id: 'reading', label: 'Reading' },
  { id: 'problem_set', label: 'Problem set' },
  { id: 'lecture_notes', label: 'Lecture notes' },
  { id: 'revision', label: 'Revision' },
  { id: 'writing', label: 'Writing' },
  { id: 'coding', label: 'Coding' },
] as const
export type GoalId = (typeof GOALS)[number]['id']

/** ?demo=1 runs every timer in seconds instead of minutes, with its own separate storage. */
export function isDemo(search: string): boolean {
  return new URLSearchParams(search).get('demo') === '1'
}

/** The running experiment: docs/experiments/EXP-001.md. */
export const EXPERIMENT_KEY = 'exp-001'

/**
 * ?demo=1&variant=test previews an experiment arm. Demo mode is never enrolled and its events
 * are dropped from analysis, so a preview sends no exposure and is never counted.
 */
export function previewVariant(search: string): 'control' | 'test' | null {
  const params = new URLSearchParams(search)
  const variant = params.get('variant')
  return isDemo(search) && (variant === 'control' || variant === 'test') ? variant : null
}
