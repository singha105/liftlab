// localStorage can throw (Safari private mode, blocked site data, full quota). When it does,
// the app keeps working from an in-memory copy for the rest of the page's life.
const memory = new Map<string, string>()

export function readJSON(key: string): unknown {
  let raw: string | null | undefined
  try {
    raw = localStorage.getItem(key)
  } catch {
    raw = memory.get(key)
  }
  if (raw == null) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function writeJSON(key: string, value: unknown): void {
  const raw = JSON.stringify(value)
  memory.set(key, raw)
  try {
    localStorage.setItem(key, raw)
  } catch {
    // Already kept in memory above.
  }
}
