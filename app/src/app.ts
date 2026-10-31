import * as analytics from './analytics'
import {
  DEFAULT_LENGTH,
  EXPERIMENT_KEY,
  GOALS,
  LENGTHS,
  isDemo,
  previewVariant,
  type GoalId,
  type SessionLength,
} from './config'
import { endsAt, focusedMs, remainingMs, type ActiveSession } from './session'
import { loadState, saveState, type Arm, type State } from './state'
import {
  DAY_MS,
  addDays,
  currentStreak,
  dayKey,
  longestStreak,
  weekStart,
  weekTotals,
  type DayTotals,
} from './time'

const RING_LENGTH = 2 * Math.PI * 54
const HISTORY_DAYS_KEPT = 400

function el<T extends Element = HTMLElement>(id: string): T {
  const node = document.getElementById(id)
  if (!node) throw new Error(`Missing #${id}`)
  return node as unknown as T
}

const ui = {
  demoBanner: el('demo-banner'),
  streakButton: el<HTMLButtonElement>('streak-button'),
  streakLabel: el('streak-label'),
  screens: {
    setup: el('screen-setup'),
    timer: el('screen-timer'),
    done: el('screen-done'),
  },
  headings: {
    setup: el('setup-title'),
    timer: el('timer-title'),
    done: el('done-title'),
  },
  lengths: el('lengths'),
  goals: el('goals'),
  start: el<HTMLButtonElement>('start'),
  summaryButton: el<HTMLButtonElement>('summary-button'),
  timerTime: el('timer-time'),
  timerStatus: el('timer-status'),
  ring: el<SVGCircleElement>('ring-progress'),
  pause: el<HTMLButtonElement>('pause'),
  giveUp: el<HTMLButtonElement>('give-up'),
  doneDetail: el('done-detail'),
  doneStreak: el('done-streak'),
  again: el<HTMLButtonElement>('again'),
  doneHome: el<HTMLButtonElement>('done-home'),
  giveUpDialog: el<HTMLDialogElement>('give-up-dialog'),
  awayDialog: el<HTMLDialogElement>('away-dialog'),
  awayDetail: el('away-detail'),
  streakDialog: el<HTMLDialogElement>('streak-dialog'),
  streakDetails: el('streak-details'),
  summaryDialog: el<HTMLDialogElement>('summary-dialog'),
  summaryTitle: el('summary-title'),
  summaryRange: el('summary-range'),
  summarySessions: el('summary-sessions'),
  summaryMinutes: el('summary-minutes'),
  summaryBars: el('summary-bars'),
  summaryCompare: el('summary-compare'),
  analyticsNote: el('analytics-note'),
  analyticsToggle: el<HTMLButtonElement>('analytics-toggle'),
}

type Screen = keyof typeof ui.screens | 'quick'

let unitMs = 60_000
let storageKey = 'studysprint'
let state: State
let selectedLength: SessionLength
let selectedGoal: GoalId | null
let ticker: number | undefined
// EXP-001: this device's arm (or a demo preview), and whether the start screen has been
// touched or "Customize" chosen on this page load.
let arm: Arm | null = null
let setupTouched = false
let customized = false
let quick: { section: HTMLElement; heading: HTMLElement } | null = null

const today = () => dayKey(Date.now())
const streakNow = () => currentStreak(state.history, today())
const save = () => saveState(storageKey, state)
const goalLabel = (id: GoalId | null) => GOALS.find((g) => g.id === id)?.label ?? null

export function startApp(): void {
  const demo = isDemo(location.search)
  unitMs = demo ? 1000 : 60_000
  storageKey = demo ? 'studysprint:demo' : 'studysprint'
  state = loadState(storageKey)
  selectedLength = state.lastLength
  selectedGoal = state.lastGoal
  const isFirstOpen = state.firstOpenAt === null
  state.firstOpenAt ??= Date.now()
  const enrolled = state.experiments[EXPERIMENT_KEY] ?? null
  arm = previewVariant(location.search) ?? enrolled

  ui.demoBanner.hidden = !demo
  buildSetup()
  bindEvents()
  showSetup(false)
  const loadMs = Math.round(performance.now())

  analytics.initAnalytics({
    app_version: (import.meta.env.VITE_APP_VERSION || 'dev').slice(0, 7),
    experiment_key: enrolled ? EXPERIMENT_KEY : 'none',
    variant: enrolled ?? 'none',
    is_demo: demo,
  })
  renderFooter()
  analytics.trackAppOpened({
    is_first_open: isFirstOpen,
    load_ms: loadMs,
    referrer_type: analytics.referrerType(document.referrer, location.hostname),
    current_streak_days: streakNow(),
  })

  resumeActiveSession()
  if (!state.active) maybeOpenWeeklySummary()
  save()
  if (isFirstOpen && !demo) void joinExperiment()
}

// ---- EXP-001: Quick Start --------------------------------------------------------------

/**
 * The exposure rule from docs/experiments/EXP-001.md: on a device's first open, once the flag
 * has loaded, if the start screen is still untouched. Every check happens before the arm is
 * known, so both arms are filtered the same way. Control sees nothing change.
 */
async function joinExperiment(): Promise<void> {
  const variant = await analytics.getVariant(EXPERIMENT_KEY)
  if (!variant || setupTouched || state.active || state.sessionsStarted > 0) return
  arm = variant
  state.experiments[EXPERIMENT_KEY] = variant
  save()
  analytics.setExperimentContext(EXPERIMENT_KEY, variant)
  if (variant === 'test') showSetup(false)
  analytics.trackExperimentExposed({ experiment_key: EXPERIMENT_KEY, variant })
}

/** The test arm, until the first session starts or the user asks to customize. */
function quickStartOn(): boolean {
  return arm === 'test' && state.sessionsStarted === 0 && !customized
}

/** Built only for the test arm, so the control page stays exactly as it was. */
function quickScreen(): { section: HTMLElement; heading: HTMLElement } {
  if (quick) return quick
  const section = document.createElement('section')
  section.id = 'screen-quick'
  section.className = 'screen'
  section.setAttribute('aria-labelledby', 'quick-title')
  section.innerHTML = `
    <h1 id="quick-title" tabindex="-1">Start a focus sprint</h1>
    <p class="lede">One click and the timer starts. Stay with one thing for ${DEFAULT_LENGTH} minutes.</p>
    <button id="quick-start" class="button primary quick-start" type="button">Start a ${DEFAULT_LENGTH}-minute focus</button>
    <button id="customize" class="button quiet" type="button">Customize length or goal</button>`
  ui.screens.setup.after(section)
  section.querySelector('#quick-start')?.addEventListener('click', () => {
    selectedLength = DEFAULT_LENGTH
    selectedGoal = null
    startSession('quick_start')
  })
  section.querySelector('#customize')?.addEventListener('click', () => {
    customized = true
    showSetup()
  })
  quick = { section, heading: el('quick-title') }
  return quick
}

// ---- Setup -----------------------------------------------------------------------------

function buildSetup(): void {
  ui.lengths.replaceChildren(
    ...LENGTHS.map((length) => {
      const label = document.createElement('label')
      label.className = 'length'
      const input = document.createElement('input')
      input.type = 'radio'
      input.name = 'length'
      input.value = String(length)
      input.addEventListener('change', () => {
        selectedLength = length
        setupTouched = true
        syncSetup()
      })
      const text = document.createElement('span')
      text.innerHTML = `<strong>${length}</strong> min`
      label.append(input, text)
      return label
    }),
  )
  ui.goals.replaceChildren(
    ...GOALS.map((goal) => {
      const chip = document.createElement('button')
      chip.type = 'button'
      chip.className = 'chip'
      chip.textContent = goal.label
      chip.dataset.goal = goal.id
      chip.addEventListener('click', () => {
        selectedGoal = selectedGoal === goal.id ? null : goal.id
        setupTouched = true
        syncSetup()
      })
      return chip
    }),
  )
}

function syncSetup(): void {
  for (const input of ui.lengths.querySelectorAll('input')) {
    input.checked = Number(input.value) === selectedLength
  }
  for (const chip of ui.goals.querySelectorAll<HTMLButtonElement>('.chip')) {
    chip.setAttribute('aria-pressed', String(chip.dataset.goal === selectedGoal))
  }
  ui.start.textContent = `Start ${selectedLength}-minute sprint`
  const streak = streakNow()
  ui.streakLabel.textContent = streak > 0 ? `${streak}-day streak` : 'No streak yet'
}

function showSetup(moveFocus = true): void {
  syncSetup()
  showScreen(quickStartOn() ? 'quick' : 'setup', moveFocus)
}

function showScreen(screen: Screen, moveFocus: boolean): void {
  for (const [name, section] of Object.entries(ui.screens)) section.hidden = name !== screen
  const quickSection = screen === 'quick' ? quickScreen().section : quick?.section
  if (quickSection) quickSection.hidden = screen !== 'quick'
  ui.streakButton.hidden = screen !== 'setup' && screen !== 'quick'
  if (screen !== 'timer') stopTicker()
  if (moveFocus) (screen === 'quick' ? quickScreen().heading : ui.headings[screen]).focus()
}

// ---- Session lifecycle -----------------------------------------------------------------

function newSessionId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  // randomUUID needs a secure context; plain-http LAN testing on a phone doesn't have one.
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = ((b[6] ?? 0) & 0x0f) | 0x40
  b[8] = ((b[8] ?? 0) & 0x3f) | 0x80
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

function startSession(method: 'preset' | 'quick_start' = 'preset'): void {
  if (state.active) return
  const session: ActiveSession = {
    id: newSessionId(),
    plannedMinutes: selectedLength,
    goal: selectedGoal,
    startedAt: Date.now(),
    pausedAt: null,
    pausedMs: 0,
    pauseCount: 0,
  }
  state.active = session
  state.sessionsStarted++
  state.lastLength = selectedLength
  state.lastGoal = selectedGoal
  save()
  analytics.trackSessionStarted({
    session_id: session.id,
    planned_minutes: session.plannedMinutes,
    goal_set: session.goal !== null,
    start_method: method,
    session_number: state.sessionsStarted,
  })
  showTimer()
}

/** A session saved by an earlier page load: resume it, or settle how it ended. */
function resumeActiveSession(): void {
  const session = state.active
  if (!session) return
  const now = Date.now()
  if (session.pausedAt !== null) {
    if (now - session.startedAt > DAY_MS) abandonSession('stale')
    else showTimer()
  } else if (remainingMs(session, now, unitMs) > 0) {
    showTimer()
  } else if (now - endsAt(session, now, unitMs) > DAY_MS) {
    abandonSession('stale')
  } else {
    // The timer ran out while no page was open: closed tab, or a phone that discarded it.
    // Only the student knows whether they kept going, so ask.
    ui.awayDetail.textContent = `Did you stay with your ${session.plannedMinutes}-minute sprint until the end?`
    openDialog(ui.awayDialog)
  }
}

function completeSession(whileAway: boolean): void {
  const session = state.active
  if (!session) return
  const now = Date.now()
  const end = Math.min(endsAt(session, now, unitMs), now)
  const day = dayKey(end)
  const totals: DayTotals = state.history[day] ?? { sessions: 0, minutes: 0 }
  state.history[day] = {
    sessions: totals.sessions + 1,
    minutes: totals.minutes + session.plannedMinutes,
  }
  pruneHistory()
  const isFirstCompletion = state.sessionsCompleted === 0
  state.sessionsCompleted++
  state.longestStreak = Math.max(state.longestStreak, longestStreak(state.history))
  state.active = null
  save()
  // The timer can run out while "Give up?" is still open; finishing wins.
  if (ui.giveUpDialog.open) ui.giveUpDialog.close()

  const streak = streakNow()
  analytics.trackSessionCompleted(
    {
      session_id: session.id,
      planned_minutes: session.plannedMinutes,
      actual_minutes: Math.round((end - session.startedAt) / unitMs),
      pause_count: session.pauseCount,
      goal_set: session.goal !== null,
      current_streak_days: streak,
      is_first_completion: isFirstCompletion,
      completed_while_away: whileAway,
    },
    new Date(end),
  )

  const goal = goalLabel(session.goal)
  ui.doneDetail.textContent = goal
    ? `${session.plannedMinutes} minutes of ${goal.toLowerCase()}.`
    : `${session.plannedMinutes} minutes of focus.`
  renderStreak(ui.doneStreak, 7)
  showScreen('done', true)
  analytics.trackStreakViewed({
    current_streak_days: streak,
    longest_streak_days: state.longestStreak,
    surface: 'completion_screen',
  })
}

function abandonSession(reason: 'user_ended' | 'page_closed' | 'stale'): void {
  const session = state.active
  if (!session) return
  const focused = Math.min(focusedMs(session, Date.now()), session.plannedMinutes * unitMs)
  state.active = null
  save()
  analytics.trackSessionAbandoned({
    session_id: session.id,
    planned_minutes: session.plannedMinutes,
    // In demo mode a second stands in for a minute, so durations are scaled the same way.
    elapsed_seconds: Math.round((focused / unitMs) * 60),
    pause_count: session.pauseCount,
    goal_set: session.goal !== null,
    reason,
  })
}

function pruneHistory(): void {
  const cutoff = addDays(today(), -HISTORY_DAYS_KEPT)
  for (const day of Object.keys(state.history)) {
    if (day < cutoff) delete state.history[day]
  }
}

// ---- Timer -----------------------------------------------------------------------------

function showTimer(): void {
  const session = state.active
  if (!session) return
  ui.headings.timer.textContent = goalLabel(session.goal) ?? 'Focus sprint'
  ui.timerStatus.textContent = ''
  syncPauseButton()
  showScreen('timer', true)
  tick()
  stopTicker()
  ticker = window.setInterval(tick, 250)
}

function stopTicker(): void {
  window.clearInterval(ticker)
  ticker = undefined
}

function tick(): void {
  const session = state.active
  // Only a session running on screen can complete here. One restored from an earlier
  // page load waits for the away check instead.
  if (!session || ui.screens.timer.hidden) return
  const left = remainingMs(session, Date.now(), unitMs)
  const seconds = Math.ceil(left / 1000)
  ui.timerTime.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
  const done = 1 - left / (session.plannedMinutes * unitMs)
  ui.ring.style.strokeDashoffset = String(RING_LENGTH * (1 - done))
  if (left === 0 && session.pausedAt === null) completeSession(false)
}

function togglePause(): void {
  const session = state.active
  if (!session) return
  const now = Date.now()
  if (session.pausedAt === null) {
    session.pausedAt = now
    session.pauseCount++
    ui.timerStatus.textContent = 'Paused'
  } else {
    session.pausedMs += now - session.pausedAt
    session.pausedAt = null
    ui.timerStatus.textContent = 'Running'
  }
  save()
  syncPauseButton()
  tick()
}

function syncPauseButton(): void {
  const paused = state.active?.pausedAt != null
  ui.pause.textContent = paused ? 'Resume' : 'Pause'
  ui.screens.timer.classList.toggle('is-paused', paused)
}

// ---- Streak and weekly summary ---------------------------------------------------------

const weekdayFormat = new Intl.DateTimeFormat(undefined, { weekday: 'narrow' })
const fullDateFormat = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
const shortDateFormat = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' })

const asDate = (key: string) => new Date(`${key}T12:00:00`)
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

function formatMinutes(total: number): string {
  if (total < 60) return `${total} min`
  const rest = total % 60
  return rest ? `${Math.floor(total / 60)} h ${rest} min` : `${total / 60} h`
}

function renderStreak(container: HTMLElement, days: number): void {
  const streak = streakNow()
  const headline = document.createElement('p')
  headline.className = 'streak-headline'
  headline.innerHTML =
    streak > 0
      ? `<strong>${streak}</strong> ${streak === 1 ? 'day' : 'days'} in a row`
      : 'No streak yet. Finish a sprint today to start one.'
  const best = document.createElement('p')
  best.className = 'muted'
  best.textContent = `Longest streak: ${plural(state.longestStreak, 'day')}`

  const list = document.createElement('ol')
  list.className = 'days'
  list.setAttribute('aria-label', `Last ${days} days`)
  for (let i = days - 1; i >= 0; i--) {
    const key = addDays(today(), -i)
    const item = document.createElement('li')
    const hit = Boolean(state.history[key])
    item.className = hit ? 'day is-done' : 'day'
    item.innerHTML = `<span class="dot" aria-hidden="true"></span><span aria-hidden="true">${weekdayFormat.format(asDate(key))}</span><span class="sr-only">${fullDateFormat.format(asDate(key))}: ${hit ? 'sprint done' : 'no sprint'}</span>`
    list.append(item)
  }
  container.replaceChildren(headline, best, list)
}

function openStreak(): void {
  renderStreak(ui.streakDetails, 14)
  openDialog(ui.streakDialog)
  analytics.trackStreakViewed({
    current_streak_days: streakNow(),
    longest_streak_days: state.longestStreak,
    surface: 'home',
  })
}

function maybeOpenWeeklySummary(): void {
  const thisWeek = weekStart(today())
  if (state.summaryWeek === thisWeek) return
  const returningInNewWeek = state.summaryWeek !== null && state.sessionsCompleted > 0
  state.summaryWeek = thisWeek
  if (returningInNewWeek) openSummary('new_week')
}

/** Opened by the user it shows this week; opened at the start of a new week it recaps last week. */
function openSummary(openedBy: 'new_week' | 'user'): void {
  const monday = weekStart(today())
  const shown = openedBy === 'new_week' ? addDays(monday, -7) : monday
  const week = weekTotals(state.history, shown)
  const before = weekTotals(state.history, addDays(shown, -7))

  ui.summaryTitle.textContent = openedBy === 'new_week' ? 'Last week' : 'This week'
  ui.summaryRange.textContent = `${shortDateFormat.format(asDate(shown))} to ${shortDateFormat.format(asDate(addDays(shown, 6)))}`
  ui.summarySessions.textContent = String(week.sessions)
  ui.summaryMinutes.textContent = formatMinutes(week.minutes)
  ui.summaryCompare.textContent = `${openedBy === 'new_week' ? 'Week before' : 'Last week'}: ${plural(before.sessions, 'sprint')}, ${formatMinutes(before.minutes)}.`

  const peak = Math.max(1, ...week.perDay)
  ui.summaryBars.setAttribute('aria-label', 'Sprints per day')
  ui.summaryBars.replaceChildren(
    ...week.perDay.map((count, i) => {
      const key = addDays(shown, i)
      const item = document.createElement('li')
      item.style.setProperty('--fill', String(count / peak))
      item.innerHTML = `<span class="bar" aria-hidden="true"></span><span aria-hidden="true">${weekdayFormat.format(asDate(key))}</span><span class="sr-only">${fullDateFormat.format(asDate(key))}: ${plural(count, 'sprint')}</span>`
      return item
    }),
  )

  openDialog(ui.summaryDialog)
  analytics.trackWeeklySummaryViewed({
    sessions_completed_week: week.sessions,
    focus_minutes_week: week.minutes,
    opened_by: openedBy,
  })
}

// ---- Footer, dialogs and events --------------------------------------------------------

const ANALYTICS_NOTES: Record<analytics.AnalyticsStatus, string> = {
  on: 'Usage events go to PostHog to help improve the app.',
  no_key: "Analytics aren't set up in this build, so nothing is sent.",
  dnt: 'Your browser asks sites not to track you, so nothing is sent.',
  opted_out: "You've turned analytics off on this device, so nothing is sent.",
}

function renderFooter(): void {
  const status = analytics.analyticsStatus()
  ui.analyticsNote.textContent = ANALYTICS_NOTES[status]
  ui.analyticsToggle.hidden = status !== 'on' && status !== 'opted_out'
  ui.analyticsToggle.textContent = status === 'on' ? 'Turn off analytics' : 'Turn analytics back on'
}

function openDialog(dialog: HTMLDialogElement): void {
  dialog.returnValue = ''
  dialog.showModal()
}

function bindEvents(): void {
  ui.start.addEventListener('click', () => startSession())
  ui.again.addEventListener('click', () => startSession())
  ui.doneHome.addEventListener('click', () => showSetup())
  ui.summaryButton.addEventListener('click', () => openSummary('user'))
  ui.streakButton.addEventListener('click', openStreak)
  ui.pause.addEventListener('click', togglePause)
  ui.giveUp.addEventListener('click', () => openDialog(ui.giveUpDialog))

  ui.giveUpDialog.addEventListener('close', () => {
    if (ui.giveUpDialog.returnValue !== 'give-up') return
    abandonSession('user_ended')
    showSetup()
  })
  ui.awayDialog.addEventListener('close', () => {
    // Escape counts as "No": a completion has to be confirmed.
    if (ui.awayDialog.returnValue === 'yes') {
      completeSession(true)
    } else {
      abandonSession('page_closed')
      showSetup()
    }
  })
  ui.analyticsToggle.addEventListener('click', () => {
    analytics.setAnalyticsEnabled(analytics.analyticsStatus() !== 'on')
    renderFooter()
  })
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') tick()
  })
}
