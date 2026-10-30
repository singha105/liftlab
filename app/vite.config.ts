import { defineConfig } from 'vitest/config'

export default defineConfig({
  // Served from https://singha105.github.io/liftlab/
  base: '/liftlab/',
  // The tracking-plan test reads ../docs/TRACKING_PLAN.md.
  server: { fs: { allow: ['.', '../docs'] } },
  test: {
    environment: 'jsdom',
  },
})
