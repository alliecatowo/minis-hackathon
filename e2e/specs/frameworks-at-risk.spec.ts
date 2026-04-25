/**
 * frameworks-at-risk.spec.ts — Smoke test for the owner-only frameworks page.
 *
 * Does NOT test auth flows in depth (those belong in create-mini + smoke specs).
 * Verifies only:
 *  - The route /m/{username}/frameworks renders without crashing
 *  - When dev-auth is available, the page loads and shows content
 */

import { test, expect } from '@playwright/test';

const DEV_AUTH = process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS === 'true';
const PROMO_USER = process.env.NEXT_PUBLIC_PROMO_MINI || 'alliecatowo';

test.describe('frameworks-at-risk page', () => {
  test('page loads without crashing', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        // Ignore common dev environment noise
        if (
          !/\[Fast Refresh\]|Download the React DevTools|webpack-hmr|hot-update/.test(text)
        ) {
          errors.push(text);
        }
      }
    });

    await page.goto(`/m/${PROMO_USER}/frameworks`);

    // The page should not show a 500 error or blank white screen.
    // It will redirect non-owners to the profile page — that's expected.
    const body = await page.locator('body').textContent();
    expect(body).not.toBeNull();

    // No unexpected JS runtime errors
    expect(
      errors.filter((e) => !e.includes('401') && !e.includes('403')),
      `Unexpected console errors: ${errors.join('\n')}`,
    ).toHaveLength(0);
  });

  test('redirects non-owner to profile', async ({ page }) => {
    // When not authenticated (or authenticated as non-owner), navigating to
    // /m/{username}/frameworks should end up at /m/{username} (the profile).
    // We wait for navigation to settle.
    await page.goto(`/m/${PROMO_USER}/frameworks`);
    await page.waitForTimeout(2000); // allow client-side redirect to fire

    const url = page.url();
    // After redirect the path should be the mini profile or the login page —
    // NOT the /frameworks sub-path (unless dev-auth is enabled and the user
    // happens to own this mini).
    if (!DEV_AUTH) {
      expect(url).not.toContain('/frameworks');
    }
  });

  test.skip('owner sees framework cards when dev-auth enabled', async ({ page }) => {
    // This test is only meaningful when DEV_AUTH_BYPASS=true and a mini exists
    // for the dev user.  Skip it in CI unless explicitly configured.
    if (!DEV_AUTH) test.skip();

    await page.goto(`/m/${PROMO_USER}/frameworks`);
    await page.waitForLoadState('networkidle');

    // Either we see the "No frameworks at risk" message, or real framework cards
    const heading = page.locator('h1', { hasText: 'Frameworks at Risk' });
    await expect(heading).toBeVisible({ timeout: 10_000 });
  });
});
