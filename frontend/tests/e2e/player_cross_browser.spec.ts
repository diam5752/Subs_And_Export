import { expect, test } from '@playwright/test';
import el from '@/i18n/el.json';
import { mockApi, stabilizeUi } from './mocks';

test('player and subtitle manipulation stay clear across browser engines', async ({
  page,
}, testInfo) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const phone = page.getByTestId('editor-phone');
  const video = phone.locator('video');
  const overlay = page.getByTestId('subtitle-overlay');
  const isTouchProject = testInfo.project.name === 'android-chromium'
    || testInfo.project.name === 'ios-webkit';

  await expect(phone).toBeVisible();
  await expect(overlay).toBeVisible();
  expect(await video.getAttribute('controls')).toBeNull();
  await expect(page.getByTestId('editor-preview-controls')).toHaveCount(0);
  await expect(page.getByText(el.subtitlesReady, { exact: true })).toHaveCount(0);
  await expect(page.locator('.subtitle-edit-affordance')).toHaveCount(0);

  const phoneBox = await phone.boundingBox();
  expect(phoneBox).not.toBeNull();
  expect(phoneBox!.width).toBeGreaterThanOrEqual(180);
  expect(phoneBox!.height).toBeGreaterThan(phoneBox!.width);

  const gestureY = phoneBox!.y + (phoneBox!.height * 0.22);
  const gestureStartX = phoneBox!.x + (phoneBox!.width * 0.35);
  await video.dispatchEvent('pointerdown', {
    bubbles: true,
    cancelable: true,
    pointerId: 31,
    pointerType: 'touch',
    isPrimary: true,
    button: 0,
    clientX: gestureStartX,
    clientY: gestureY,
  });
  await video.dispatchEvent('pointermove', {
    bubbles: true,
    cancelable: true,
    pointerId: 31,
    pointerType: 'touch',
    isPrimary: true,
    button: 0,
    clientX: gestureStartX + 48,
    clientY: gestureY + 1,
  });
  const seekFeedback = page.getByTestId('preview-gesture-feedback');
  await expect(seekFeedback).toBeVisible();
  await expect(seekFeedback).toContainText('/');
  await expect(seekFeedback).toContainText('−');
  await expect(page.getByTestId('preview-seek-progress')).toBeVisible();
  await video.dispatchEvent('pointerup', {
    bubbles: true,
    cancelable: true,
    pointerId: 31,
    pointerType: 'touch',
    isPrimary: true,
    button: 0,
    clientX: gestureStartX + 48,
    clientY: gestureY + 1,
  });
  await expect(page.getByTestId('preview-gesture-feedback')).toHaveCount(0);

  await video.press('Enter');
  await expect.poll(async () => video.evaluate(
    (element) => (element as HTMLVideoElement).paused,
  )).toBe(false);

  await video.dispatchEvent('pointerdown', {
    bubbles: true,
    cancelable: true,
    pointerId: 32,
    pointerType: 'touch',
    isPrimary: true,
    button: 0,
    clientX: gestureStartX,
    clientY: gestureY,
  });
  await page.waitForTimeout(400);
  await expect.poll(async () => video.evaluate(
    (element) => (element as HTMLVideoElement).playbackRate,
  )).toBe(2);
  await video.dispatchEvent('pointerup', {
    bubbles: true,
    cancelable: true,
    pointerId: 32,
    pointerType: 'touch',
    isPrimary: true,
    button: 0,
    clientX: gestureStartX,
    clientY: gestureY,
  });
  await expect.poll(async () => video.evaluate(
    (element) => (element as HTMLVideoElement).playbackRate,
  )).toBe(1);

  if (isTouchProject) {
    await expect(page.getByTestId('subtitle-drag-handle')).toBeHidden();
    await expect(page.getByTestId('subtitle-resize-handle')).toBeHidden();
    await expect(page.getByTestId('subtitle-touch-manipulation-hint')).toHaveCount(0);

    const centerX = phoneBox!.x + (phoneBox!.width / 2);
    const centerY = phoneBox!.y + (phoneBox!.height / 2);
    await overlay.dispatchEvent('pointerdown', {
      bubbles: true,
      cancelable: true,
      pointerId: 41,
      pointerType: 'touch',
      isPrimary: true,
      clientX: centerX - 40,
      clientY: centerY,
    });
    await overlay.dispatchEvent('pointerdown', {
      bubbles: true,
      cancelable: true,
      pointerId: 42,
      pointerType: 'touch',
      isPrimary: false,
      clientX: centerX + 40,
      clientY: centerY,
    });
    await overlay.dispatchEvent('pointermove', {
      bubbles: true,
      cancelable: true,
      pointerId: 42,
      pointerType: 'touch',
      isPrimary: false,
      clientX: centerX + 60,
      clientY: centerY,
    });
    await expect.poll(async () => Number(await overlay.getAttribute('data-font-size')))
      .toBeGreaterThan(100);
    await overlay.dispatchEvent('pointerup', {
      bubbles: true,
      cancelable: true,
      pointerId: 42,
      pointerType: 'touch',
      isPrimary: false,
      clientX: centerX + 60,
      clientY: centerY,
    });
    await overlay.dispatchEvent('pointerup', {
      bubbles: true,
      cancelable: true,
      pointerId: 41,
      pointerType: 'touch',
      isPrimary: true,
      clientX: centerX - 40,
      clientY: centerY,
    });

    await page.getByRole('tab', { name: el.tabStyles }).click();
    const workspace = page.getByTestId('editor-workspace');
    const previewPanel = page.getByTestId('editor-preview-panel');
    const sidebar = page.getByTestId('editor-sidebar');
    const sidebarBody = sidebar.locator('.editor-sidebar-body');

    await expect(workspace).toHaveClass(/editor-workspace-style-mode/);
    await expect.poll(async () => workspace.evaluate(
      (element) => element.getBoundingClientRect().top,
    )).toBeGreaterThanOrEqual(63);
    await expect.poll(async () => workspace.evaluate(
      (element) => element.getBoundingClientRect().top,
    )).toBeLessThanOrEqual(80);
    await expect(previewPanel).toBeVisible();
    await expect(page.getByRole('slider', { name: el.sizeLabel })).toBeVisible();
    await expect(sidebar.getByRole('status')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: el.customSettings })).toHaveCount(0);

    const previewBox = await previewPanel.boundingBox();
    const stylePhoneBox = await phone.boundingBox();
    const sidebarBox = await sidebar.boundingBox();
    expect(previewBox).not.toBeNull();
    expect(stylePhoneBox).not.toBeNull();
    expect(sidebarBox).not.toBeNull();
    expect(stylePhoneBox!.width).toBeGreaterThanOrEqual(180);
    expect(sidebarBox!.y).toBeGreaterThanOrEqual(
      previewBox!.y + previewBox!.height,
    );
    await expect(page.getByTestId('editor-export-panel')).toHaveCount(0);

    // Mobile uses the page's natural scroll. The tab row must not float over
    // settings or create a second nested scroll surface.
    await expect.poll(async () => sidebarBody.evaluate(
      (element) => getComputedStyle(element).overflowY,
    )).toBe('visible');
    await expect.poll(async () => sidebar.locator('.editor-tabs-sticky').evaluate(
      (element) => getComputedStyle(element).position,
    )).toBe('static');
    await sidebarBody.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await expect.poll(async () => sidebarBody.evaluate((element) => element.scrollTop))
      .toBe(0);
  } else {
    await expect(page.getByTestId('subtitle-drag-handle')).toBeVisible();
    await expect(page.getByTestId('subtitle-resize-handle')).toBeVisible();
  }

  await page.getByRole('button', { name: el.exportMenuButton, exact: true }).click();
  const exportMenu = page.getByTestId('editor-export-menu');
  await expect(exportMenu).toBeVisible();
  await expect(exportMenu.getByTestId('download-1080p-btn')).toBeVisible();
  await expect(exportMenu.getByTestId('download-4k-btn')).toBeVisible();
  await expect(exportMenu.getByTestId('srt-btn')).toBeVisible();
  await expect(exportMenu.getByTestId('txt-btn')).toBeVisible();
  await expect(exportMenu.getByTestId('vtt-btn')).toHaveCount(0);
  const exportMenuBox = await exportMenu.boundingBox();
  expect(exportMenuBox).not.toBeNull();
  expect(exportMenuBox!.x).toBeGreaterThanOrEqual(0);
  expect(exportMenuBox!.y).toBeGreaterThanOrEqual(0);
  expect(exportMenuBox!.x + exportMenuBox!.width).toBeLessThanOrEqual(
    page.viewportSize()!.width + 1,
  );
  expect(exportMenuBox!.y + exportMenuBox!.height).toBeLessThanOrEqual(
    page.viewportSize()!.height + 1,
  );
  await page.keyboard.press('Escape');
  await expect(exportMenu).toHaveCount(0);

  expect(await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  )).toBe(true);
});
