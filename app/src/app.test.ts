import { beforeEach, describe, expect, it, vi } from 'vitest'
import page from '../index.html?raw'

/** Renders index.html and runs a fresh copy of the app on it, as a page load would. */
async function openApp(): Promise<void> {
  document.body.innerHTML = new DOMParser().parseFromString(page, 'text/html').body.innerHTML
  vi.resetModules()
  const { startApp } = await import('./app')
  startApp()
}

beforeEach(() => {
  localStorage.clear()
})

describe('start screen', () => {
  // The snapshot was recorded from the app before EXP-001's code existed. Control has to keep
  // matching it byte for byte.
  it('is unchanged for a first-time visitor without an experiment', async () => {
    await openApp()
    await expect(document.body.innerHTML).toMatchFileSnapshot('__snapshots__/start-screen.html')
    // innerHTML doesn't show which radio is checked.
    expect(document.querySelector<HTMLInputElement>('input[name=length]:checked')?.value).toBe('25')
  })
})
