/**
 * CropSentinel — Playwright configuration
 * ═══════════════════════════════════════
 * Smoke / regression tests for the customer dashboard and platform portal.
 *
 * Assumes the Vite dev server is running on :5173 and the backend on :8000.
 * Run locally with:   npm run test:e2e
 * Debug interactively: npm run test:e2e:ui
 *
 * In CI, `webServer` starts `vite` automatically before the test run.
 */

import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir:          './e2e',
  fullyParallel:    true,
  forbidOnly:       !!process.env.CI,
  retries:          process.env.CI ? 2 : 0,
  workers:          process.env.CI ? 1 : undefined,
  reporter:         process.env.CI ? 'github' : 'list',
  timeout:          30_000,

  use: {
    baseURL:   process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace:     'on-first-retry',
    screenshot:'only-on-failure',
    video:     'retain-on-failure',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome']  } },
    { name: 'firefox',  use: { ...devices['Desktop Firefox'] } },
    // Safari optional — uncomment when we actually support it
    // { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],

  webServer: process.env.E2E_SKIP_SERVER
    ? undefined
    : {
        command:             'npm run dev',
        url:                 'http://localhost:5173',
        timeout:             120_000,
        reuseExistingServer: !process.env.CI,
      },
})
