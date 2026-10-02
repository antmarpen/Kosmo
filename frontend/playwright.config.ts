import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  fullyParallel: false,
  // The journeys share global task capacity and container resources (several
  // launch real worker tasks), so they must not race each other across files.
  workers: 1,
  retries: 1,
  reporter: 'list',
  use: { baseURL: 'http://localhost:5173', ...devices['Desktop Chrome'] },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
