import { expect, test, type Page } from '@playwright/test';
import { resolve } from 'node:path';
import { mockApi, waitForUploadWorkspace } from './mocks';
import el from '@/i18n/el.json';

const compactViewport = { width: 320, height: 568 } as const;
const fixturePath = resolve(process.cwd(), '../backend/tests/data/demo_output.mp4');

async function openGuestAuthGate(page: Page) {
  await page.goto('/');
  await waitForUploadWorkspace(page, { authenticated: false });
  await page.locator('input[type="file"]').setInputFiles(fixturePath);
  await expect(page.getByRole('heading', { name: 'demo_output.mp4' })).toBeVisible();
  await expect(page.getByTestId('video-credit-pricing')).toContainText(
    el.videoCreditPricingDuration.replace('{duration}', '0:09'),
    { timeout: 15_000 },
  );
  const startButton = page.getByRole('button', { name: new RegExp(el.startProcessing) });
  await expect(startButton).toBeEnabled();
  await startButton.click();

  const authDialog = page.getByRole('dialog', {
    name: el.processingGateAuthTitle,
  });
  await expect(authDialog).toBeVisible();
  return authDialog;
}

test.describe('Inline processing gate on mobile browsers', () => {
  test('Google signs in once, preserves the upload, and waits for cost confirmation', async ({ page }) => {
    // REGRESSION: the inline gate offered only email/password even though the
    // standalone login page supported the hardened Google nonce flow.
    let googleNonceRequests = 0;
    let googleCredentialPosts = 0;
    let processingPosts = 0;
    page.on('request', (request) => {
      const { pathname } = new URL(request.url());
      if (pathname === '/auth/google/nonce') googleNonceRequests += 1;
      if (pathname === '/auth/google' && request.method() === 'POST') {
        googleCredentialPosts += 1;
      }
      if (/\/videos\/process(?:-stream)?$/.test(pathname) && request.method() === 'POST') {
        processingPosts += 1;
      }
    });

    await mockApi(page, { authenticated: false });
    const authDialog = await openGuestAuthGate(page);
    const googleButton = authDialog.getByRole('button', { name: 'Σύνδεση με Google' });

    await expect(googleButton).toBeVisible();
    await expect.poll(() => googleNonceRequests).toBe(1);

    const createAccountButton = authDialog.getByRole('button', {
      name: el.processingGateCreateAccount,
    });
    const lockedRootOffset = await page.evaluate(() => window.scrollY);
    // REGRESSION: iOS WebKit could move the root scroller while making a
    // control actionable, leaving the modal visible but offsetting hit tests
    // so <html> intercepted the following pointer click.
    await page.evaluate((attemptedOffset) => {
      document.documentElement.scrollTop = attemptedOffset;
      window.dispatchEvent(new Event('scroll'));
    }, lockedRootOffset + 241);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(lockedRootOffset);
    await createAccountButton.click();
    await expect(authDialog.getByRole('button', {
      name: el.processingGateUseLogin,
    })).toBeVisible();
    await expect(googleButton).toBeVisible();

    await authDialog.getByRole('button', {
      name: el.processingGateUseLogin,
    }).click();
    await expect(authDialog.getByRole('button', {
      name: el.processingGateCreateAccount,
    })).toBeVisible();
    await expect(googleButton).toBeVisible();
    await page.evaluate(() => new Promise<void>((resolveFrame) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolveFrame()));
    }));
    expect(googleNonceRequests).toBe(1);

    await googleButton.click();

    const costDialog = page.getByRole('dialog', {
      name: el.processingGateCostTitle,
    });
    await expect(costDialog).toBeVisible();
    await expect.poll(() => googleCredentialPosts).toBe(1);
    expect(processingPosts).toBe(0);
    await expect(
      page.locator('[data-testid="upload-section"] h4', { hasText: 'demo_output.mp4' }),
    ).toBeVisible();

    const processingRequest = page.waitForRequest((request) => (
      request.method() === 'POST'
      && /\/videos\/process(?:-stream)?$/.test(new URL(request.url()).pathname)
    ));
    await costDialog.getByRole('button', {
      name: new RegExp(el.processingGateConfirm.replace('{cost}', '\\d+')),
    }).click();
    await processingRequest;
    await expect.poll(() => processingPosts).toBe(1);
    expect(googleCredentialPosts).toBe(1);
  });

  test('locks the document and keeps the compact dialog contained and reachable', async (
    { page },
    testInfo,
  ) => {
    // REGRESSION: setting only body overflow hidden did not lock the background
    // in iOS WebViews, and the taller auth card could escape a short viewport.
    await page.setViewportSize(compactViewport);
    await mockApi(page, { authenticated: false });
    await page.goto('/');
    await waitForUploadWorkspace(page, { authenticated: false });
    await page.addStyleTag({
      content: 'body::after { content: ""; display: block; height: 1400px; }',
    });
    await page.locator('input[type="file"]').setInputFiles(fixturePath);
    await expect(page.getByTestId('video-credit-pricing')).toContainText(
      el.videoCreditPricingDuration.replace('{duration}', '0:09'),
      { timeout: 15_000 },
    );
    const startButton = page.getByRole('button', { name: new RegExp(el.startProcessing) });
    await expect(startButton).toBeEnabled();
    await page.evaluate(() => window.scrollTo(0, 360));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);

    const originalState = await startButton.evaluate((button) => {
      const state = {
        scrollX: window.scrollX,
        scrollY: window.scrollY,
        rootOverflow: document.documentElement.style.overflow,
        rootOverscroll: document.documentElement.style.overscrollBehavior,
        rootHeight: document.documentElement.style.height,
        bodyOverflow: document.body.style.overflow,
        bodyPosition: document.body.style.position,
        bodyTop: document.body.style.top,
        bodyLeft: document.body.style.left,
        bodyWidth: document.body.style.width,
        bodyHeight: document.body.style.height,
        bodyOverscroll: document.body.style.overscrollBehavior,
      };
      // Keep the scroll snapshot and event atomic. Locator.click() scrolls an
      // off-screen button into view before dispatching, which would measure
      // Playwright's helper movement instead of the application's lock.
      (button as HTMLButtonElement).click();
      return state;
    });
    const dialog = page.getByTestId('processing-gate');
    const card = page.getByTestId('processing-gate-card');
    await expect(dialog).toBeVisible();
    await expect(card).toBeVisible();
    await dialog.getByRole('button', {
      name: el.processingGateCreateAccount,
    }).click();

    const lockedState = await page.evaluate(() => {
      const rootStyle = getComputedStyle(document.documentElement);
      const bodyStyle = getComputedStyle(document.body);
      const bodyRect = document.body.getBoundingClientRect();
      return {
        rootOverflow: rootStyle.overflow,
        rootOverscroll: rootStyle.overscrollBehavior,
        bodyOverflow: bodyStyle.overflow,
        bodyOverscroll: bodyStyle.overscrollBehavior,
        bodyPosition: bodyStyle.position,
        bodyTop: bodyStyle.top,
        bodyRectTop: bodyRect.top,
        rootHeight: document.documentElement.style.height,
        bodyHeight: document.body.style.height,
        windowScrollX: window.scrollX,
        windowScrollY: window.scrollY,
      };
    });
    expect(lockedState.rootOverflow).toBe('hidden');
    expect(lockedState.rootOverscroll).toBe('none');
    expect(lockedState.bodyOverflow).toBe('hidden');
    expect(lockedState.bodyOverscroll).toBe('none');
    expect(lockedState.bodyPosition).toBe('fixed');
    expect(lockedState.rootHeight).toBe('100%');
    expect(lockedState.bodyHeight).toBe('100%');
    expect(Number.parseFloat(lockedState.bodyTop)).toBeCloseTo(-originalState.scrollY, 0);

    const layout = await page.evaluate(() => {
      const dialogElement = document.querySelector<HTMLElement>('[data-testid="processing-gate"]');
      const cardElement = document.querySelector<HTMLElement>('[data-testid="processing-gate-card"]');
      if (!dialogElement || !cardElement) throw new Error('Processing gate layout is missing');
      const cardRect = cardElement.getBoundingClientRect();
      return {
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        documentOverflow: document.documentElement.scrollWidth
          - document.documentElement.clientWidth,
        dialogOverflow: dialogElement.scrollWidth - dialogElement.clientWidth,
        cardOverflow: cardElement.scrollWidth - cardElement.clientWidth,
        cardLeft: cardRect.left,
        cardRight: cardRect.right,
        cardTop: cardRect.top,
        cardBottom: cardRect.bottom,
        cardClientHeight: cardElement.clientHeight,
        cardScrollHeight: cardElement.scrollHeight,
        cardOverflowY: getComputedStyle(cardElement).overflowY,
      };
    });
    expect(layout.documentOverflow).toBeLessThanOrEqual(1);
    expect(layout.dialogOverflow).toBeLessThanOrEqual(1);
    expect(layout.cardOverflow).toBeLessThanOrEqual(1);
    expect(layout.cardLeft).toBeGreaterThanOrEqual(0);
    expect(layout.cardRight).toBeLessThanOrEqual(layout.viewportWidth + 1);
    expect(layout.cardTop).toBeGreaterThanOrEqual(0);
    expect(layout.cardBottom).toBeLessThanOrEqual(layout.viewportHeight + 1);
    expect(layout.cardOverflowY).toMatch(/auto|scroll/);
    expect(layout.cardScrollHeight).toBeGreaterThan(layout.cardClientHeight);

    const backgroundBeforeAttempt = await page.evaluate(() => ({
      bodyRectTop: document.body.getBoundingClientRect().top,
      bodyTop: getComputedStyle(document.body).top,
      scrollX: window.scrollX,
      scrollY: window.scrollY,
    }));
    if (testInfo.project.name === 'ios-webkit') {
      // Mobile WebKit intentionally has no synthetic mouse wheel API. Exercise
      // its touch path and directly challenge the locked root scroller.
      await dialog.dispatchEvent('touchstart', { cancelable: true, bubbles: true });
      await dialog.dispatchEvent('touchmove', { cancelable: true, bubbles: true });
      await page.evaluate(() => window.scrollBy(0, 900));
    } else {
      await page.mouse.move(2, 2);
      await page.mouse.wheel(0, 900);
    }
    await page.keyboard.press('PageDown');
    const backgroundAfterAttempt = await page.evaluate(() => ({
      bodyRectTop: document.body.getBoundingClientRect().top,
      bodyTop: getComputedStyle(document.body).top,
      scrollX: window.scrollX,
      scrollY: window.scrollY,
    }));
    expect(backgroundAfterAttempt).toEqual(backgroundBeforeAttempt);

    await card.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await expect.poll(() => card.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    const tailButton = dialog.getByRole('button', { name: el.processingGateUseLogin });
    await expect(tailButton).toBeVisible();
    const [tailBox, cardBox] = await Promise.all([
      tailButton.boundingBox(),
      card.boundingBox(),
    ]);
    expect(tailBox).not.toBeNull();
    expect(cardBox).not.toBeNull();
    expect(tailBox!.y).toBeGreaterThanOrEqual(cardBox!.y - 1);
    expect(tailBox!.y + tailBox!.height)
      .toBeLessThanOrEqual(cardBox!.y + cardBox!.height + 1);

    await card.evaluate((element) => {
      element.scrollTop = 0;
    });
    await dialog.getByRole('button', { name: el.closeLabel }).click();
    await expect(dialog).toBeHidden();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(originalState.scrollY);

    const restoredState = await page.evaluate(() => ({
      scrollX: window.scrollX,
      scrollY: window.scrollY,
      rootOverflow: document.documentElement.style.overflow,
      rootOverscroll: document.documentElement.style.overscrollBehavior,
      rootHeight: document.documentElement.style.height,
      bodyOverflow: document.body.style.overflow,
      bodyPosition: document.body.style.position,
      bodyTop: document.body.style.top,
      bodyLeft: document.body.style.left,
      bodyWidth: document.body.style.width,
      bodyHeight: document.body.style.height,
      bodyOverscroll: document.body.style.overscrollBehavior,
    }));
    expect(restoredState).toEqual(originalState);
  });
});
