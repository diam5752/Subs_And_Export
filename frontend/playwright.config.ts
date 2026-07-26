import { defineConfig } from '@playwright/test';

export const DEFAULT_PLAYWRIGHT_PORT = 31873;

export function resolvePlaywrightPort(rawPort: string | undefined): number {
  if (rawPort === undefined) {
    return DEFAULT_PLAYWRIGHT_PORT;
  }

  if (!/^\d+$/.test(rawPort)) {
    throw new Error('PLAYWRIGHT_PORT must be an integer between 1 and 65535.');
  }

  const port = Number(rawPort);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
    throw new Error('PLAYWRIGHT_PORT must be an integer between 1 and 65535.');
  }

  return port;
}

const playwrightPort = resolvePlaywrightPort(process.env.PLAYWRIGHT_PORT);
const playwrightHost = '127.0.0.1';
const playwrightBaseUrl = `http://${playwrightHost}:${playwrightPort}`;

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : 4,
  reporter: process.env.CI ? 'github' : 'list',
  snapshotPathTemplate: '{testDir}/{testFileDir}/{testFileName}-snapshots/{arg}{ext}',
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.02,
    },
  },
  use: {
    baseURL: playwrightBaseUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
        viewport: { width: 1280, height: 800 },
        colorScheme: 'light',
      },
    },
  ],
  webServer: {
    // Exercise the production bundle and avoid development HMR replacing pages
    // while the long, multi-page browser suite is still running.
    command: (
      `npm run build && npm run start -- `
      + `--hostname ${playwrightHost} --port ${playwrightPort}`
    ),
    url: playwrightBaseUrl,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
