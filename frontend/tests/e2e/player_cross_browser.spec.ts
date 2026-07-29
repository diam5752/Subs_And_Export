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
  await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const phone = page.getByTestId('editor-phone');
  const video = phone.locator('video');
  const controls = page.getByTestId('editor-preview-controls');
  const overlay = page.getByTestId('subtitle-overlay');
  const isTouchProject = testInfo.project.name === 'android-chromium'
    || testInfo.project.name === 'ios-webkit';

  await expect(phone).toBeVisible();
  await expect(overlay).toBeVisible();
  await expect(controls).toBeVisible();
  expect(await video.getAttribute('controls')).toBeNull();
  await expect(page.locator('.subtitle-edit-affordance')).toHaveCount(0);
  await expect(page.getByTestId('editor-preview-time')).toContainText('/');

  const phoneBox = await phone.boundingBox();
  const controlsBox = await controls.boundingBox();
  expect(phoneBox).not.toBeNull();
  expect(controlsBox).not.toBeNull();
  expect(controlsBox!.y).toBeGreaterThanOrEqual(phoneBox!.y + phoneBox!.height);

  const controlButtons = controls.getByRole('button');
  await expect(controlButtons).toHaveCount(2);
  for (let index = 0; index < 2; index += 1) {
    const buttonBox = await controlButtons.nth(index).boundingBox();
    expect(buttonBox).not.toBeNull();
    expect(buttonBox!.width).toBeGreaterThanOrEqual(44);
    expect(buttonBox!.height).toBeGreaterThanOrEqual(44);
  }

  if (isTouchProject) {
    await expect(page.getByTestId('subtitle-drag-handle')).toBeHidden();
    await expect(page.getByTestId('subtitle-resize-handle')).toBeHidden();
    await expect(page.getByTestId('subtitle-touch-manipulation-hint')).toBeVisible();

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
  } else {
    await expect(page.getByTestId('subtitle-drag-handle')).toBeVisible();
    await expect(page.getByTestId('subtitle-resize-handle')).toBeVisible();
  }

  expect(await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  )).toBe(true);
});
