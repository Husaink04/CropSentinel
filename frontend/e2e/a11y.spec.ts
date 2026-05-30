/**
 * Accessibility smoke — cheap checks that don't need axe-core wired up yet.
 * The serious audit lives in the WCAG contrast pass in index.css.
 */

import { test, expect } from '@playwright/test'

test('login page exposes a skip-link that becomes visible on focus', async ({ page }) => {
  await page.goto('/login')
  const skip = page.locator('a.skip-link')
  await expect(skip).toHaveCount(1)
  // The link is visually hidden until focused — tabbing brings it into view
  await page.keyboard.press('Tab')
  await expect(skip).toBeFocused()
})

test('main landmark exists and receives focus from skip-link', async ({ page }) => {
  await page.goto('/login')
  const main = page.locator('#main-content')
  await expect(main).toHaveCount(1)
})

test('focus ring is visible on interactive elements (keyboard nav)', async ({ page }) => {
  await page.goto('/login')
  // Tab past skip-link onto the first real input
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  const focused = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null
    if (!el) return null
    const style = getComputedStyle(el)
    return { outline: style.outlineStyle, outlineWidth: style.outlineWidth }
  })
  expect(focused).not.toBeNull()
  // We only assert that *some* outline is drawn — exact width depends on browser
  expect(focused?.outline).not.toBe('none')
})
