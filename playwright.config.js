const { defineConfig, devices } = require('@playwright/test');

const baseURL = process.env.EDIFY_E2E_BASE_URL || 'http://127.0.0.1:8000';

module.exports = defineConfig({
  testDir: './e2e',
  outputDir: 'test-results/artifacts',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000,
  expect: { timeout: 8_000 },
  reporter: [
    ['line'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['json', { outputFile: 'test-results/results.json' }],
  ],
  use: {
    baseURL,
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    reducedMotion: 'reduce',
  },
  projects: [
    // Clears each seeded account's first-login agreements before any journey
    // signs in (see e2e/seeded-accounts.setup.js). Runs in Chromium whichever
    // browser project depends on it.
    {
      name: 'seeded-accounts',
      testMatch: /seeded-accounts\.setup\.js/,
      use: { ...devices['Desktop Chrome'] },
    },
    { name: 'chromium-desktop', dependencies: ['seeded-accounts'], use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox-desktop', dependencies: ['seeded-accounts'], use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit-desktop', dependencies: ['seeded-accounts'], use: { ...devices['Desktop Safari'] } },
    { name: 'android-360', dependencies: ['seeded-accounts'], use: { ...devices['Galaxy S9+'] } },
    { name: 'iphone-390', dependencies: ['seeded-accounts'], use: { ...devices['iPhone 13'] } },
    {
      name: 'tablet-768',
      dependencies: ['seeded-accounts'],
      use: {
        ...devices['iPad (gen 7)'],
        viewport: { width: 768, height: 1024 },
      },
    },
  ],
});
