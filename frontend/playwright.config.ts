import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  fullyParallel: false,
  retries: 1,
  reporter: 'list',
  use: { baseURL: 'http://localhost:5173', ...devices['Desktop Chrome'] },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
