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
