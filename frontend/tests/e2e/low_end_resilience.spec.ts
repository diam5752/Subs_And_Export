import { expect, test } from '@playwright/test';
import { statSync } from 'node:fs';
import { resolve } from 'node:path';
import { mockApi } from './mocks';
import el from '@/i18n/el.json';

type LowEndMetrics = {
  cls: number;
  longTasks: number[];
};

type LowEndMeasurement = {
  readyMs: number;
  cls: number;
  approxTbt: number;
  horizontalOverflow: number;
  backdropFilter: string;
  videoDuration: number;
  videoWidth: number;
  p95FrameMs: number;
  framesOver50Ms: number;
};

const LOW_END_SAMPLE_COUNT = 3;

test('a transient initial session failure exposes retry and then restores the user', async ({ page }) => {
  // REGRESSION: a stored bearer plus a failed /auth/me request previously left
  // the production shell on "Φόρτωση..." without a bounded recovery action.
  await mockApi(page);
  let authAttempts = 0;
  await page.route('**/auth/me', async (route) => {
    authAttempts += 1;
    if (authAttempts === 1) {
      await route.abort('timedout');
      return;
    }
    await route.fallback();
  });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: el.sessionUnavailableTitle })).toBeVisible();
  await expect(page.getByRole('button', { name: el.sessionRetry })).toBeVisible();
  await expect(page.getByText(el.loading, { exact: true })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => localStorage.getItem('auth_token')))
    .toBe('test-token');

  await page.getByRole('button', { name: el.sessionRetry }).click();

  await expect(page.getByRole('button', { name: el.profileLabel })).toBeVisible();
  await expect(page.getByRole('heading', { name: el.sessionUnavailableTitle })).toHaveCount(0);
  expect(authAttempts).toBe(2);
});

test('the completed editor stays within low-end mobile performance budgets with real media', {
  tag: '@performance',
}, async ({ page }) => {
  test.setTimeout(60_000);
  const mediaFixture = resolve(process.cwd(), '../backend/tests/data/demo_output.mp4');
  expect(statSync(mediaFixture).size).toBeGreaterThan(7_000_000);

  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
    Object.defineProperty(navigator, 'hardwareConcurrency', {
      configurable: true,
      value: 2,
    });
    const metrics: LowEndMetrics = { cls: 0, longTasks: [] };
    (window as typeof window & { __lowEndMetrics?: LowEndMetrics }).__lowEndMetrics = metrics;
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const shift = entry as PerformanceEntry & {
            value: number;
            hadRecentInput: boolean;
          };
          if (!shift.hadRecentInput) metrics.cls += shift.value;
        }
      }).observe({ type: 'layout-shift', buffered: true });
    } catch {
      // Older supported engines may not expose layout-shift entries.
    }
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) metrics.longTasks.push(entry.duration);
      }).observe({ type: 'longtask', buffered: true });
    } catch {
      // Long-task observation is a Chromium-only diagnostic enhancement.
    }
  });
  await page.setViewportSize({ width: 390, height: 844 });

  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 6 });
  await cdp.send('Network.enable');
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  const measurements: LowEndMeasurement[] = [];

  try {
    for (let sampleIndex = 0; sampleIndex < LOW_END_SAMPLE_COUNT; sampleIndex += 1) {
      await cdp.send('Network.clearBrowserCache');
      if (sampleIndex > 0) await page.goto('about:blank');

      const startedAt = Date.now();
      await page.goto('/');
      await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
      await page.waitForFunction(() => {
        const video = document.querySelector('video');
        return Boolean(video && video.readyState >= 1 && video.duration > 0);
      });
      const readyMs = Date.now() - startedAt;

      const scrollFrames = await page.evaluate(() => new Promise<number[]>((resolveFrames) => {
        const frames: number[] = [];
        const started = performance.now();
        let previous = started;
        const maxScroll = Math.max(0, document.documentElement.scrollHeight - innerHeight);
        const sample = (now: number) => {
          frames.push(now - previous);
          previous = now;
          const progress = Math.min(1, (now - started) / 1_200);
          const cycle = progress <= 0.5 ? progress * 2 : (1 - progress) * 2;
          scrollTo(0, maxScroll * cycle);
          if (progress < 1) requestAnimationFrame(sample);
          else resolveFrames(frames);
        };
        requestAnimationFrame(sample);
      }));

      measurements.push(await page.evaluate(({ readyMs: sampleReadyMs, scrollFrames: frames }) => {
        const metrics = (window as typeof window & { __lowEndMetrics?: LowEndMetrics })
          .__lowEndMetrics ?? { cls: 0, longTasks: [] };
        const video = document.querySelector('video');
        const header = document.querySelector<HTMLElement>('.studio-header');
        const sortedFrames = [...frames].sort((a, b) => a - b);
        return {
          readyMs: sampleReadyMs,
          cls: metrics.cls,
          approxTbt: metrics.longTasks.reduce(
            (total, duration) => total + Math.max(0, duration - 50),
            0,
          ),
          horizontalOverflow:
            document.documentElement.scrollWidth - document.documentElement.clientWidth,
          backdropFilter: header ? getComputedStyle(header).backdropFilter : '',
          videoDuration: video?.duration ?? 0,
          videoWidth: video?.videoWidth ?? 0,
          p95FrameMs: sortedFrames[Math.floor(sortedFrames.length * 0.95)] ?? 0,
          framesOver50Ms: sortedFrames.filter((duration) => duration > 50).length,
        };
      }, { readyMs, scrollFrames }));
    }
  } finally {
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
    await cdp.send('Network.setCacheDisabled', { cacheDisabled: false });
    await cdp.send('Network.disable');
  }

  const sortedTbt = measurements.map((sample) => sample.approxTbt).sort((a, b) => a - b);
  const medianTbt = sortedTbt[Math.floor(sortedTbt.length / 2)] ?? Number.POSITIVE_INFINITY;
  await test.info().attach('low-end-metrics.json', {
    body: JSON.stringify({ medianTbt, samples: measurements }, null, 2),
    contentType: 'application/json',
  });
  console.info('Low-end mobile metrics:', { medianTbt, samples: measurements });

  // Keep deterministic visual and readiness failures strict on every sample.
  // TBT uses the median of three cache-disabled samples so one shared-runner
  // scheduling pause cannot turn an otherwise identical build into a flake.
  for (const measurement of measurements) {
    expect(measurement.readyMs).toBeLessThan(10_000);
    expect(measurement.cls).toBeLessThanOrEqual(0.1);
    expect(measurement.horizontalOverflow).toBeLessThanOrEqual(1);
    expect(measurement.backdropFilter).toBe('none');
    expect(measurement.videoDuration).toBeGreaterThan(8);
    expect(measurement.videoWidth).toBeGreaterThan(0);
    expect(measurement.p95FrameMs).toBeLessThanOrEqual(35);
    expect(measurement.framesOver50Ms).toBeLessThanOrEqual(1);
  }
  expect(medianTbt).toBeLessThanOrEqual(350);
});
