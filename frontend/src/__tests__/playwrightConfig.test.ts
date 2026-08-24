/** @jest-environment node */

import config, {
  DEFAULT_PLAYWRIGHT_PORT,
  resolvePlaywrightPort,
} from '../../playwright.config';
import qualityGates from '../../../.codex/quality-gates.json';

describe('Playwright server isolation', () => {
  test('uses a dedicated server and never reuses an existing process', () => {
    // REGRESSION: local E2E previously reused any server already listening on port 3000.
    const webServer = Array.isArray(config.webServer)
      ? config.webServer[0]
      : config.webServer;

    expect(DEFAULT_PLAYWRIGHT_PORT).toBe(31873);
    expect(config.use?.baseURL).toBe('http://127.0.0.1:31873');
    // REGRESSION: the production PWA worker could claim an E2E page and bypass
    // page.route(), sending mocked auth requests to the Next server as 404s.
    expect(config.use?.serviceWorkers).toBe('block');
    expect(config.failOnFlakyTests).toBe(Boolean(process.env.CI));
    expect(webServer).toMatchObject({
      command: (
        'npm run build && npm run start -- '
        + '--hostname 127.0.0.1 --port 31873'
      ),
      env: {
        NEXT_PUBLIC_API_URL: '',
        NEXT_PUBLIC_TRANSCRIBE_PROVIDER: 'mock',
        NEXT_PUBLIC_TRANSCRIBE_MODE: 'standard',
      },
      reuseExistingServer: false,
      url: 'http://127.0.0.1:31873',
    });
    // REGRESSION: an ignored local provider override made the mock E2E suite
    // execute the external-provider flow and fail nondeterministically.
  });

  test('rejects invalid port overrides before a browser server can start', () => {
    expect(resolvePlaywrightPort(undefined)).toBe(31873);
    expect(resolvePlaywrightPort('31999')).toBe(31999);

    for (const invalidPort of ['', '0', '65536', '3000.5', 'not-a-port']) {
      expect(() => resolvePlaywrightPort(invalidPort)).toThrow(
        'PLAYWRIGHT_PORT must be an integer between 1 and 65535.',
      );
    }
  });

  test('pins the canonical quality gate to the isolated port', () => {
    expect(qualityGates.commands['check:e2e']).toMatchObject({
      kind: 'shell',
      shell: 'cd frontend && PLAYWRIGHT_PORT=31873 npm run e2e',
      status: 'enabled',
    });
    expect(qualityGates.commands['check:all'].steps).toContain('check:e2e');
  });

  test('keeps focused player and modal coverage on their required browser engines', () => {
    const projects = config.projects ?? [];
    expect(projects.map((project) => project.name)).toEqual([
      'chromium',
      'android-chromium',
      'ios-webkit',
      'desktop-firefox',
      'low-end-chromium',
    ]);
    expect(projects).toEqual(expect.arrayContaining([
      expect.objectContaining({
        name: 'android-chromium',
        testMatch: /(?:player|modal)_cross_browser\.spec\.ts/,
        use: expect.objectContaining({ browserName: 'chromium', hasTouch: true }),
      }),
      expect.objectContaining({
        name: 'ios-webkit',
        testMatch: /(?:player|modal)_cross_browser\.spec\.ts/,
        use: expect.objectContaining({ browserName: 'webkit', hasTouch: true }),
      }),
      expect.objectContaining({
        name: 'desktop-firefox',
        testMatch: /player_cross_browser\.spec\.ts/,
        use: expect.objectContaining({ browserName: 'firefox' }),
      }),
      expect.objectContaining({
        name: 'low-end-chromium',
        testMatch: /low_end_resilience\.spec\.ts/,
        grep: /@performance/,
        dependencies: [
          'chromium',
          'android-chromium',
          'ios-webkit',
          'desktop-firefox',
        ],
        use: expect.objectContaining({ browserName: 'chromium' }),
      }),
    ]));
    expect(projects[0]).toMatchObject({
      name: 'chromium',
      grepInvert: /@performance/,
    });
  });
});
