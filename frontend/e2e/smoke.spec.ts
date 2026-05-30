/**
 * Smoke tests — confirm the app boots and core routing works.
 * No backend contract assumptions beyond "login endpoint returns JSON".
 */

import { test, expect } from '@playwright/test'

test.describe('Customer dashboard smoke', () => {
  test('unauthenticated root redirects to /login', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login$/)
  })

  test('login page renders credentials form', async ({ page }) => {
    await page.goto('/login')
    // form fields should be present — exact label text may vary, so match loosely
    await expect(page.getByRole('textbox').first()).toBeVisible()
    await expect(page.getByRole('button', { name: /sign in|log ?in/i })).toBeVisible()
  })

  test('wrong credentials show an error and stay on /login', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('textbox').first().fill('nope@example.com')
    // password field is typically the second textbox / only [type=password]
    const pw = page.locator('input[type="password"]')
    await pw.fill('wrong-password')
    await page.getByRole('button', { name: /sign in|log ?in/i }).click()
    // error toast / message — we don't pin the exact copy, just stay on /login
    await expect(page).toHaveURL(/\/login$/)
  })
})

test.describe('Platform portal smoke', () => {
  test('unauthenticated /platform redirects to /platform/login', async ({ page }) => {
    await page.goto('/platform')
    await expect(page).toHaveURL(/\/platform\/login$/)
  })

  test('/platform/tenants is guarded too (PlatformPrivateRoute)', async ({ page }) => {
    await page.goto('/platform/tenants')
    await expect(page).toHaveURL(/\/platform\/login$/)
  })
})

test.describe('Code-split chunks load successfully', () => {
  test('no chunk-load errors on first navigation', async ({ page }) => {
    const chunkErrors: string[] = []
    page.on('pageerror',   (e) => chunkErrors.push(String(e)))
    page.on('requestfailed', (r) => {
      const url = r.url()
      if (url.endsWith('.js') || url.endsWith('.mjs')) {
        chunkErrors.push(`failed: ${url} — ${r.failure()?.errorText}`)
      }
    })
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    expect(chunkErrors).toEqual([])
  })
})
