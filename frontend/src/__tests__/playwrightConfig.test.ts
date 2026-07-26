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
    expect(webServer).toMatchObject({
      command: 'npm run dev -- --hostname 127.0.0.1 --port 31873',
      reuseExistingServer: false,
      url: 'http://127.0.0.1:31873',
    });
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
});
