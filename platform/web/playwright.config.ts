/**
 * The browser comparison of the Next.js pages with the existing web's.
 * Local only: it needs the existing web (Django), the gateway and this app
 * running on this machine, and seed accounts. CI does not run it.
 *
 *   EDIFY_COMPARE_PASSWORD=… EDIFY_COMPARE_OUT=/some/dir npm run test:compare
 */
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  outputDir: 'test-results',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  reporter: [['line']],
  use: { trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop-1440', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'phone-390', use: { ...devices['iPhone 13'], browserName: 'chromium', viewport: { width: 390, height: 844 } } },
  ],
});
