import { defineConfig, devices } from '@playwright/test';

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
  failOnFlakyTests: !!process.env.CI,
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
    // The production bundle registers the PWA worker. A claimed worker can
    // bypass page.route(), so mocked API requests may reach the Next server
    // instead of the deterministic E2E handlers.
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      // The throttled benchmark runs only after every functional project so
      // host contention cannot masquerade as main-thread work in its TBT data.
      grepInvert: /@performance/,
      use: {
        browserName: 'chromium',
        viewport: { width: 1280, height: 800 },
        colorScheme: 'light',
      },
    },
    {
      name: 'android-chromium',
      // Keep mobile-only regressions bounded to the surfaces that need real
      // Android Chromium coverage instead of multiplying the full E2E suite.
      testMatch: /(?:player|modal)_cross_browser\.spec\.ts/,
      use: {
        ...devices['Pixel 7'],
        browserName: 'chromium',
        colorScheme: 'light',
      },
    },
    {
      name: 'ios-webkit',
      // REGRESSION: body-only overflow locking passed desktop Chromium while
      // the inline auth gate still moved the page in an iOS mail WebView.
      testMatch: /(?:player|modal)_cross_browser\.spec\.ts/,
      use: {
        ...devices['iPhone 13'],
        browserName: 'webkit',
        colorScheme: 'light',
      },
    },
    {
      name: 'desktop-firefox',
      testMatch: /player_cross_browser\.spec\.ts/,
      use: {
        browserName: 'firefox',
        viewport: { width: 1280, height: 800 },
        colorScheme: 'light',
      },
    },
    {
      name: 'low-end-chromium',
      testMatch: /low_end_resilience\.spec\.ts/,
      grep: /@performance/,
      dependencies: [
        'chromium',
        'android-chromium',
        'ios-webkit',
        'desktop-firefox',
      ],
      use: {
        browserName: 'chromium',
        viewport: { width: 390, height: 844 },
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
    env: {
      // Keep release E2E deterministic even when a developer has an
      // ignored .env.local configured for a real paid provider.
      NEXT_PUBLIC_API_URL: '',
      NEXT_PUBLIC_TRANSCRIBE_PROVIDER: 'mock',
      NEXT_PUBLIC_TRANSCRIBE_MODE: 'standard',
    },
    url: playwrightBaseUrl,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
