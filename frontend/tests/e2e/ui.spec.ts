import { expect, test, type Page } from '@playwright/test';
import { mockApi, stabilizeUi, waitForDashboardShell, waitForUploadWorkspace } from './mocks';
import el from '@/i18n/el.json';

const viewports = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
} as const;

const editorViewportMatrix = [
  { width: 320, height: 568 },
  { width: 375, height: 667 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

test('Beta status and testing notice stay discreet and readable', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/');
  await waitForUploadWorkspace(page, { authenticated: false });

  await expect(page.getByTestId('beta-badge')).toHaveText(el.betaBadge);
  await expect(page.getByText(el.betaTestingNotice)).toBeVisible();

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await stabilizeUi(page);
    await expectNoHorizontalOverflow(page);
    const badge = page.getByTestId('beta-badge');
    await expect(badge).toBeVisible();
    const badgeBox = await badge.boundingBox();
    expect(badgeBox).not.toBeNull();
    expect(badgeBox?.height ?? 0).toBeLessThanOrEqual(18);
  }
});

test('Google Identity Services login exchanges an ID token for a GSUBS session', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/login');

  await page.getByRole('button', { name: 'Σύνδεση με Google' }).click();

  await expect.poll(() => page.evaluate(() => localStorage.getItem('auth_token')))
    .toBe('google-token');
  await expect(page).toHaveURL('/');
  // REGRESSION: the authenticated header must render the profile image
  // returned after the Google session refresh.
  await expect(page.getByTestId('profile-avatar-image')).toBeVisible();
});

test('expired Google nonce requires a full reload and never posts the stale credential', async ({ page }) => {
  // REGRESSION: a login tab left open past the nonce TTL used to send the old
  // credential, fail with an English backend detail, and require a manual retry.
  let googleNonceRequests = 0;
  let googleCredentialPosts = 0;
  page.on('request', (request) => {
    const { pathname } = new URL(request.url());
    if (pathname === '/auth/google/nonce') googleNonceRequests += 1;
    if (pathname === '/auth/google' && request.method() === 'POST') {
      googleCredentialPosts += 1;
    }
  });

  await mockApi(page, { authenticated: false, googleNonceExpiresIn: 1 });
  await page.goto('/login');
  await expect(page.getByRole('button', { name: 'Σύνδεση με Google' })).toBeVisible();

  await expect(page.getByRole('status')).toContainText(el.loginGoogleExpired, {
    timeout: 3_000,
  });
  await page.evaluate(() => {
    const browserWindow = window as typeof window & {
      __mockGoogleCallback?: (response: { credential?: string }) => void;
    };
    browserWindow.__mockGoogleCallback?.({
      credential: 'signed-e2e-google-id-token',
    });
  });
  await page.waitForTimeout(100);
  expect(googleCredentialPosts).toBe(0);

  const mainFrameReloaded = page.waitForEvent('framenavigated', (frame) => (
    frame === page.mainFrame()
  ));
  await page.getByRole('button', { name: el.loginGoogleReload }).click();
  await mainFrameReloaded;
  await expect.poll(() => googleNonceRequests).toBeGreaterThanOrEqual(2);
});

test('Google sign-in stays contained when the auth viewport shrinks', async ({ page }) => {
  await page.setViewportSize(viewports.desktop);
  await mockApi(page, { authenticated: false });
  await page.goto('/login');

  const googleContainer = page.getByTestId('google-button-container');
  await expect(googleContainer).toBeVisible();

  // Match the important part of the real GSI markup: its iframe can retain the
  // desktop width and includes a transparent 10px gutter on both sides.
  await googleContainer.evaluate((container) => {
    const wrapper = document.createElement('div');
    const iframe = document.createElement('iframe');
    iframe.title = 'Google sign-in';
    iframe.style.width = '370px';
    iframe.style.height = '44px';
    wrapper.appendChild(iframe);
    container.replaceChildren(wrapper);
  });

  for (const viewport of [
    { width: 320, height: 568 },
    { width: 390, height: 844 },
    { width: 430, height: 932 },
    { width: 768, height: 1024 },
  ]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }));

    const metrics = await page.evaluate(() => {
      const bounds = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) throw new Error(`Missing responsive auth element: ${selector}`);
        const rect = element.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width };
      };

      return {
        documentOverflow: document.documentElement.scrollWidth
          - document.documentElement.clientWidth,
        main: bounds('.auth-main'),
        card: bounds('.auth-card'),
        googleContainer: bounds('[data-testid="google-button-container"]'),
        googleIframe: bounds('[data-testid="google-button-container"] iframe'),
      };
    });

    expect(metrics.documentOverflow, `${viewport.width}px document overflow`)
      .toBeLessThanOrEqual(1);
    for (const region of [metrics.main, metrics.card, metrics.googleIframe]) {
      expect(region.left, `${viewport.width}px left containment`).toBeGreaterThanOrEqual(0);
      expect(region.right, `${viewport.width}px right containment`)
        .toBeLessThanOrEqual(viewport.width + 1);
    }
    expect(
      metrics.googleIframe.width,
      `${viewport.width}px Google iframe width`,
    ).toBeLessThanOrEqual(metrics.googleContainer.width + 20.5);
  }
});

async function expectNoHorizontalOverflow(page: Page, selector?: string) {
  const overflow = await page.evaluate((sel) => {
    const target = sel ? document.querySelector<HTMLElement>(sel) : document.documentElement;
    if (!target) return 0;
    const clientWidth = target.clientWidth || window.innerWidth;
    return target.scrollWidth - clientWidth;
  }, selector);
  expect(overflow).toBeLessThanOrEqual(1);
}

test('completed editor remains readable across the responsive viewport matrix', async ({ page }) => {
  test.setTimeout(60_000);
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });

  await page.setViewportSize(editorViewportMatrix[0]);
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  for (const viewport of editorViewportMatrix) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }));

    const metrics = await page.evaluate(() => {
      const bounds = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) throw new Error(`Missing responsive editor element: ${selector}`);
        const rect = element.getBoundingClientRect();
        return {
          x: rect.x,
          y: rect.y,
          right: rect.right,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
        };
      };

      return {
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        intro: bounds('[data-testid="studio-intro"]'),
        introDisplay: getComputedStyle(
          document.querySelector<HTMLElement>('[data-testid="studio-intro"]')!,
        ).display,
        stepper: bounds('[data-testid="workflow-stepper"]'),
        stepperDisplay: getComputedStyle(
          document.querySelector<HTMLElement>('[data-testid="workflow-stepper"]')!,
        ).display,
        section: bounds('#preview-section'),
        duplicateStepHeaders: document.querySelectorAll('.editor-step-toggle').length,
        previewMetaCount: document.querySelectorAll('.editor-preview-meta').length,
        preview: bounds('[data-testid="editor-preview-panel"]'),
        phone: bounds('[data-testid="editor-phone"]'),
        sidebar: bounds('[data-testid="editor-sidebar"]'),
        tabsSticky: bounds('.editor-tabs-sticky'),
        transcriptList: bounds('.editor-transcript-list'),
        firstCueIdCount: document.querySelectorAll('#cue-0').length,
        tabs: Array.from(document.querySelectorAll<HTMLElement>('.editor-tab')).map((element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        }),
        actionBar: bounds('.editor-ready-actions'),
        newVideo: bounds('.editor-new-video'),
        exportTrigger: bounds('.editor-export-trigger'),
        persistentExportPanels: document.querySelectorAll('.editor-export-panel').length,
        headerActions: [
          bounds('.language-toggle'),
          bounds('.studio-credit-balance'),
          bounds('.profile-trigger'),
        ],
        cueActions: Array.from(document.querySelectorAll<HTMLElement>(
          '.cue-time-button, .cue-text-button, .cue-edit-button',
        )).map((element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        }),
        subtitleTouchSurface: (() => {
          const trigger = document.querySelector<HTMLElement>('.subtitle-inline-trigger');
          if (!trigger) return null;
          const pseudo = getComputedStyle(trigger, '::before');
          return { content: pseudo.content, top: pseudo.top, left: pseudo.left };
        })(),
      };
    });

    // REGRESSION: the old desktop layout gave almost all width to the fixed sidebar,
    // leaving the video and export controls in an unusable sliver.
    expect(metrics.documentOverflow, `${viewport.width}px document overflow`).toBeLessThanOrEqual(1);
    expect(metrics.section.x, `${viewport.width}px section left edge`).toBeGreaterThanOrEqual(0);
    expect(metrics.section.right, `${viewport.width}px section right edge`).toBeLessThanOrEqual(viewport.width + 1);
    expect(metrics.introDisplay, `${viewport.width}px completed workspace hero`).toBe('none');
    expect(metrics.intro.height, `${viewport.width}px completed workspace hero height`).toBe(0);
    expect(metrics.duplicateStepHeaders, `${viewport.width}px duplicate step headings`).toBe(0);
    expect(metrics.previewMetaCount, `${viewport.width}px preview labels`).toBe(0);
    expect(metrics.persistentExportPanels, `${viewport.width}px persistent export panels`).toBe(0);
    expect(metrics.phone.width, `${viewport.width}px phone width`).toBeGreaterThanOrEqual(
      viewport.width <= 640 && viewport.height <= 700 ? 160 : 190,
    );
    expect(metrics.phone.width, `${viewport.width}px phone width`).toBeLessThanOrEqual(280);
    // REGRESSION: the sticky tab header overlapped the beginning of the
    // transcript, clipping the timestamp and first subtitle row.
    expect(metrics.transcriptList.y, `${viewport.width}px transcript below sticky tabs`)
      .toBeGreaterThanOrEqual(metrics.tabsSticky.bottom - 1);
    expect(metrics.firstCueIdCount, `${viewport.width}px unique first cue id`).toBe(1);
    expect(metrics.newVideo.x, `${viewport.width}px new video left alignment`)
      .toBeLessThan(metrics.exportTrigger.x);
    expect(metrics.newVideo.x, `${viewport.width}px new video action containment`)
      .toBeGreaterThanOrEqual(metrics.actionBar.x);
    expect(metrics.exportTrigger.right, `${viewport.width}px export action containment`)
      .toBeLessThanOrEqual(metrics.actionBar.right + 1);

    for (const action of [...metrics.tabs, metrics.newVideo, metrics.exportTrigger]) {
      expect(action.height, `${viewport.width}px touch target height`).toBeGreaterThanOrEqual(44);
      expect(action.width, `${viewport.width}px touch target width`).toBeGreaterThanOrEqual(42);
    }

    if (viewport.width <= 800) {
      for (const action of metrics.headerActions) {
        expect(action.height, `${viewport.width}px mobile header touch target height`)
          .toBeGreaterThanOrEqual(44);
        expect(action.width, `${viewport.width}px mobile header touch target width`)
          .toBeGreaterThanOrEqual(44);
      }
      for (const action of metrics.cueActions) {
        expect(action.height, `${viewport.width}px cue touch target height`)
          .toBeGreaterThanOrEqual(44);
        expect(action.width, `${viewport.width}px cue touch target width`)
          .toBeGreaterThanOrEqual(44);
      }
      expect(metrics.subtitleTouchSurface, `${viewport.width}px subtitle touch surface`)
        .toEqual(expect.objectContaining({
          content: '""',
          top: '-16px',
          left: '-12px',
        }));
    }

    if (viewport.width >= 900) {
      expect(metrics.stepperDisplay, `${viewport.width}px desktop workflow breadcrumb`)
        .not.toBe('none');
      expect(metrics.stepper.bottom, `${viewport.width}px stepper order`)
        .toBeLessThanOrEqual(metrics.section.y + 1);
      expect(metrics.preview.width, `${viewport.width}px desktop preview width`).toBeGreaterThanOrEqual(278);
      expect(metrics.sidebar.width, `${viewport.width}px desktop controls width`).toBeGreaterThanOrEqual(480);
      expect(metrics.preview.right, `${viewport.width}px desktop column order`).toBeLessThanOrEqual(metrics.sidebar.x + 1);
    } else {
      if (viewport.width <= 640) {
        expect(metrics.stepperDisplay, `${viewport.width}px compact mobile workspace`)
          .toBe('none');
      } else {
        expect(metrics.stepperDisplay, `${viewport.width}px tablet workflow breadcrumb`)
          .not.toBe('none');
      }
      expect(metrics.preview.bottom, `${viewport.width}px mobile preview order`).toBeLessThanOrEqual(metrics.sidebar.y + 1);
      expect(metrics.tabsSticky.y, `${viewport.width}px editor tabs visible in first viewport`)
        .toBeLessThan(viewport.height);
    }

    await page.getByRole('button', { name: el.exportMenuButton, exact: true }).click();
    const exportMenu = page.getByTestId('editor-export-menu');
    await expect(exportMenu).toBeVisible();
    const exportMetrics = await exportMenu.evaluate((menu) => {
      const menuRect = menu.getBoundingClientRect();
      const actions = Array.from(menu.querySelectorAll<HTMLElement>('.editor-export-action'))
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        });
      return {
        left: menuRect.left,
        right: menuRect.right,
        top: menuRect.top,
        bottom: menuRect.bottom,
        actions,
        vttOptions: menu.querySelectorAll('[data-testid="vtt-btn"]').length,
      };
    });
    expect(exportMetrics.left, `${viewport.width}px export menu left containment`)
      .toBeGreaterThanOrEqual(0);
    expect(exportMetrics.right, `${viewport.width}px export menu right containment`)
      .toBeLessThanOrEqual(viewport.width + 1);
    expect(exportMetrics.top, `${viewport.width}px export menu top containment`)
      .toBeGreaterThanOrEqual(0);
    expect(exportMetrics.bottom, `${viewport.width}px export menu bottom containment`)
      .toBeLessThanOrEqual(viewport.height + 1);
    expect(exportMetrics.vttOptions, `${viewport.width}px public VTT option`).toBe(0);
    expect(exportMetrics.actions).toHaveLength(5);
    for (const action of exportMetrics.actions) {
      expect(action.height, `${viewport.width}px export touch target height`).toBeGreaterThanOrEqual(44);
      expect(action.width, `${viewport.width}px export touch target width`).toBeGreaterThanOrEqual(42);
    }
    await page.keyboard.press('Escape');
    await expect(exportMenu).toHaveCount(0);

    if (viewport.width <= 430) {
      await page.getByRole('tab', { name: el.tabStyles }).click();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, '[data-testid="editor-sidebar"]');
      await expect(page.getByRole('slider', { name: el.sizeLabel })).toBeVisible();
      await expect(page.getByRole('heading', { name: el.customSettings })).toHaveCount(0);
      for (const removedPreset of ['TikTok Pro', 'Cinematic Master', 'Podcast Style', 'Τελευταία Χρήση']) {
        await expect(page.getByText(removedPreset, { exact: true })).toHaveCount(0);
      }
      await page.getByRole('tab', { name: el.tabTranscript }).click();
    }
  }
});

test('desktop preview stays fixed when switching between transcript and style', async ({ page }) => {
  // REGRESSION: the taller transcript sidebar vertically centered the phone,
  // while the natural-height style sidebar moved it almost 100px upward.
  await page.setViewportSize(viewports.desktop);
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const readPreviewPosition = () => page.evaluate(() => {
    const phone = document.querySelector<HTMLElement>('[data-testid="editor-phone"]');
    const workspace = document.querySelector<HTMLElement>('[data-testid="editor-workspace"]');
    if (!phone || !workspace) throw new Error('Missing editor preview geometry');
    return {
      phoneTop: phone.getBoundingClientRect().top,
      workspaceTop: workspace.getBoundingClientRect().top,
      scrollY: window.scrollY,
    };
  });

  const transcriptPosition = await readPreviewPosition();

  await page.getByRole('tab', { name: el.tabStyles }).click();
  await stabilizeUi(page);
  const stylePosition = await readPreviewPosition();
  expect(
    Math.abs(
      (stylePosition.phoneTop - stylePosition.workspaceTop)
      - (transcriptPosition.phoneTop - transcriptPosition.workspaceTop),
    ),
    `transcript=${JSON.stringify(transcriptPosition)} style=${JSON.stringify(stylePosition)}`,
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs(
      (stylePosition.phoneTop + stylePosition.scrollY)
      - (transcriptPosition.phoneTop + transcriptPosition.scrollY),
    ),
    `transcript=${JSON.stringify(transcriptPosition)} style=${JSON.stringify(stylePosition)}`,
  ).toBeLessThanOrEqual(1);

  await page.getByRole('tab', { name: el.tabTranscript }).click();
  await stabilizeUi(page);
  const restoredTranscriptPosition = await readPreviewPosition();
  expect(
    Math.abs(
      (restoredTranscriptPosition.phoneTop - restoredTranscriptPosition.workspaceTop)
      - (transcriptPosition.phoneTop - transcriptPosition.workspaceTop),
    ),
    `initial=${JSON.stringify(transcriptPosition)} restored=${JSON.stringify(restoredTranscriptPosition)}`,
  ).toBeLessThanOrEqual(1);
});

test('logo protects an active editor before returning to the home workspace', async ({ page }) => {
  // REGRESSION: the logo behaved as an unconditional link and offered no safe
  // way to cancel when a project was already open.
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });

  const homeLink = page.getByRole('link', { name: el.brandHomeLabel });
  await homeLink.click();
  const dialog = page.getByRole('dialog', { name: el.homeNavigationModalTitle });
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId('completed-editor')).toBeVisible();

  await dialog.getByRole('button', { name: el.homeNavigationCancel }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId('completed-editor')).toBeVisible();

  await homeLink.click();
  await dialog.getByRole('button', { name: el.homeNavigationConfirm }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId('completed-editor')).toHaveCount(0);
  await waitForUploadWorkspace(page);
  await expect.poll(() => page.evaluate(() => localStorage.getItem('lastActiveJobId')))
    .toBeNull();
});

test('desktop style controls use their natural height without an empty sidebar', async ({ page }) => {
  await page.setViewportSize({ width: 2048, height: 1152 });
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await page.getByRole('tab', { name: el.tabStyles }).click();
  await stabilizeUi(page);

  const metrics = await page.evaluate(() => {
    const workspace = document.querySelector<HTMLElement>('[data-testid="editor-workspace"]');
    const preview = document.querySelector<HTMLElement>('[data-testid="editor-preview-panel"]');
    const sidebar = document.querySelector<HTMLElement>('[data-testid="editor-sidebar"]');
    const sidebarBody = document.querySelector<HTMLElement>('.editor-sidebar-body');
    const tabContent = document.querySelector<HTMLElement>('.editor-tab-content');

    if (!workspace || !preview || !sidebar || !sidebarBody || !tabContent) {
      throw new Error('Missing completed editor layout element');
    }

    const workspaceRect = workspace.getBoundingClientRect();
    const previewRect = preview.getBoundingClientRect();
    const sidebarRect = sidebar.getBoundingClientRect();
    const tabContentRect = tabContent.getBoundingClientRect();

    return {
      workspaceHeight: workspaceRect.height,
      previewHeight: previewRect.height,
      previewBackgroundColor: getComputedStyle(preview).backgroundColor,
      sidebarHeight: sidebarRect.height,
      sidebarBottomGap: sidebarRect.bottom - tabContentRect.bottom,
      sidebarBodyClientHeight: sidebarBody.clientHeight,
      sidebarBodyScrollHeight: sidebarBody.scrollHeight,
      persistentExportPanels: document.querySelectorAll('[data-testid="editor-export-panel"]').length,
    };
  });

  // REGRESSION: a fixed desktop workspace height stretched the short Styles
  // sidebar and left a large blank panel below its final control.
  expect(metrics.sidebarHeight).toBeLessThan(metrics.previewHeight);
  expect(metrics.workspaceHeight).toBeCloseTo(metrics.previewHeight, 0);
  expect(metrics.sidebarBottomGap).toBeLessThanOrEqual(20);
  expect(metrics.previewBackgroundColor).toBe('rgba(0, 0, 0, 0)');
  expect(metrics.sidebarBodyScrollHeight).toBeLessThanOrEqual(metrics.sidebarBodyClientHeight + 1);
  expect(metrics.persistentExportPanels).toBe(0);
});

test('up-to-three-line karaoke layout keeps explicit rows and non-overlapping words', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await page.getByRole('tab', { name: el.tabStyles }).click();
  const threeLineMode = page.getByRole('radio', { name: new RegExp(el.linesThree) });
  await threeLineMode.click();
  await expect(threeLineMode).toBeChecked();
  await stabilizeUi(page);

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }));

    const overlay = page.getByTestId('subtitle-overlay');
    const visibleLines = page.getByTestId('subtitle-line');
    await expect(visibleLines.first()).toBeVisible();
    const renderedLineCount = await visibleLines.count();

    // "Up to 3 Lines" is a maximum, not a request to pad shorter captions.
    // Real font metrics differ between macOS and the Linux CI runner, so this
    // fixture may correctly occupy either two or three explicit rows.
    expect(renderedLineCount).toBeGreaterThanOrEqual(1);
    expect(renderedLineCount).toBeLessThanOrEqual(3);
    await expect(overlay).toHaveAttribute('data-line-count', String(renderedLineCount));

    const metrics = await page.evaluate(() => {
      const lines = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="subtitle-line"]'));
      const words = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="subtitle-word"]'));

      const sameLineGaps = lines.flatMap((line) => {
        const lineWords = Array.from(line.querySelectorAll<HTMLElement>('[data-testid="subtitle-word"]'));
        return lineWords.slice(1).map((word, index) => {
          const previous = lineWords[index].getBoundingClientRect();
          return word.getBoundingClientRect().left - previous.right;
        });
      });

      return {
        lineOverflow: Math.max(0, ...lines.map((line) => line.scrollWidth - line.clientWidth)),
        minimumWordGap: Math.min(...sameLineGaps),
        transforms: words.map((word) => getComputedStyle(word).transform),
      };
    });

    expect(metrics.lineOverflow, `${viewport.width}px subtitle line overflow`).toBeLessThanOrEqual(1);
    expect(metrics.minimumWordGap, `${viewport.width}px karaoke word gap`).toBeGreaterThan(1);
    expect(metrics.transforms.every((transform) => transform === 'none')).toBe(true);
    await expectNoHorizontalOverflow(page);
  }

  const lineModes = [
    { name: el.lines1Word, expectedMaximum: 1 },
    { name: el.linesSingle, expectedMaximum: 1 },
    { name: el.linesDouble, expectedMaximum: 2 },
    { name: el.linesThree, expectedMaximum: 3 },
  ];

  for (const mode of lineModes) {
    await page.getByRole('radio', { name: new RegExp(mode.name) }).click();
    const visibleLines = page.getByTestId('subtitle-line');
    await expect(visibleLines.first()).toBeVisible();
    expect(await visibleLines.count(), mode.name).toBeLessThanOrEqual(mode.expectedMaximum);
  }
});

test('the active subtitle can be corrected directly on the video at mobile and desktop sizes', async ({ page }) => {
  await page.setViewportSize(viewports.mobile);
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const editTrigger = page.getByRole('button', { name: el.subtitleInlineEditAction });
  await expect(editTrigger).toBeVisible();
  await editTrigger.click();

  const inlineEditor = page.getByTestId('inline-subtitle-editor');
  const textarea = page.getByRole('textbox', { name: el.subtitleInlineTextareaLabel });
  await expect(inlineEditor).toBeVisible();
  await expect(textarea).toBeFocused();
  await expect(page.getByRole('textbox', { name: el.transcriptEdit })).not.toBeFocused();
  const focusedEditorBox = await inlineEditor.boundingBox();
  expect(focusedEditorBox).not.toBeNull();
  expect(focusedEditorBox!.y).toBeGreaterThanOrEqual(0);
  expect(focusedEditorBox!.y + focusedEditorBox!.height).toBeLessThanOrEqual(viewports.mobile.height + 1);
  await textarea.fill('ΝΕΟΣ ΣΩΣΤΟΣ ΥΠΟΤΙΤΛΟΣ');

  // The transcript panel and the editor on the video share one draft state.
  await expect(page.getByRole('textbox', { name: el.transcriptEdit })).toHaveValue('ΝΕΟΣ ΣΩΣΤΟΣ ΥΠΟΤΙΤΛΟΣ');

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await stabilizeUi(page);

    const metrics = await page.evaluate(() => {
      const phone = document.querySelector<HTMLElement>('[data-testid="editor-phone"]');
      const editor = document.querySelector<HTMLElement>('[data-testid="inline-subtitle-editor"]');
      if (!phone || !editor) throw new Error('Missing inline subtitle editor surface');
      const phoneRect = phone.getBoundingClientRect();
      const editorRect = editor.getBoundingClientRect();
      const actions = Array.from(editor.querySelectorAll<HTMLElement>('button')).map((button) => {
        const rect = button.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      });
      return {
        phone: { left: phoneRect.left, top: phoneRect.top, right: phoneRect.right, bottom: phoneRect.bottom },
        editor: { left: editorRect.left, top: editorRect.top, right: editorRect.right, bottom: editorRect.bottom },
        actions,
      };
    });

    expect(metrics.editor.left, `${viewport.width}px editor left`).toBeGreaterThanOrEqual(metrics.phone.left - 1);
    expect(metrics.editor.top, `${viewport.width}px editor top`).toBeGreaterThanOrEqual(metrics.phone.top - 1);
    expect(metrics.editor.right, `${viewport.width}px editor right`).toBeLessThanOrEqual(metrics.phone.right + 1);
    expect(metrics.editor.bottom, `${viewport.width}px editor bottom`).toBeLessThanOrEqual(metrics.phone.bottom + 1);
    for (const action of metrics.actions) {
      expect(action.width, `${viewport.width}px inline action width`).toBeGreaterThanOrEqual(44);
      expect(action.height, `${viewport.width}px inline action height`).toBeGreaterThanOrEqual(44);
    }
    await expectNoHorizontalOverflow(page);
  }

  const updateRequest = page.waitForRequest((request) => (
    request.method() === 'PUT'
    && request.url().endsWith('/videos/jobs/job-futurist/transcription')
  ));
  await textarea.press('Control+Enter');
  const request = await updateRequest;
  const payload = request.postDataJSON() as { cues: Array<{ text: string }> };
  expect(payload.cues[0].text).toBe('ΝΕΟΣ ΣΩΣΤΟΣ ΥΠΟΤΙΤΛΟΣ');

  await expect(inlineEditor).toHaveCount(0);
  await expect(page.getByRole('button', { name: el.subtitleInlineEditAction })).toContainText('ΝΕΟΣ ΣΩΣΤΟΣ ΥΠΟΤΙΤΛΟΣ');
});

test('the active subtitle can be dragged and resized directly on the desktop preview', async ({ page }) => {
  // REGRESSION: desktop users must be able to position and resize subtitles
  // with the mouse instead of relying only on sidebar sliders.
  await page.setViewportSize(viewports.desktop);
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const overlay = page.getByTestId('subtitle-overlay');
  const moveHandle = page.getByRole('slider', { name: el.subtitleDragHandleLabel });
  const resizeHandle = page.getByRole('slider', { name: el.subtitleResizeHandleLabel });
  await expect(overlay).toBeVisible();
  await expect(moveHandle).toBeVisible();
  await expect(resizeHandle).toBeVisible();
  await expect(page.getByTestId('subtitle-direct-manipulation-hint')).toHaveCount(0);

  const initialPosition = Number(await overlay.getAttribute('data-position'));
  const initialSize = Number(await overlay.getAttribute('data-font-size'));
  const overlayBox = await overlay.boundingBox();
  expect(overlayBox).not.toBeNull();

  await page.mouse.move(
    overlayBox!.x + overlayBox!.width / 2,
    overlayBox!.y + overlayBox!.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    overlayBox!.x + overlayBox!.width / 2,
    overlayBox!.y + overlayBox!.height / 2 - 55,
    { steps: 5 },
  );
  await page.mouse.up();

  await expect.poll(async () => Number(await overlay.getAttribute('data-position')))
    .toBeGreaterThan(initialPosition);

  const resizeBox = await resizeHandle.boundingBox();
  expect(resizeBox).not.toBeNull();
  await page.mouse.move(
    resizeBox!.x + resizeBox!.width / 2,
    resizeBox!.y + resizeBox!.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    resizeBox!.x + resizeBox!.width / 2 + 35,
    resizeBox!.y + resizeBox!.height / 2 + 35,
    { steps: 5 },
  );
  await page.mouse.up();

  await expect.poll(async () => Number(await overlay.getAttribute('data-font-size')))
    .toBeGreaterThan(initialSize);

  const finalPosition = Number(await overlay.getAttribute('data-position'));
  const finalSize = Number(await overlay.getAttribute('data-font-size'));
  const exportRequest = page.waitForRequest((request) => (
    request.method() === 'POST'
    && request.url().endsWith('/videos/jobs/job-futurist/export')
  ));
  await page.getByRole('button', { name: el.exportMenuButton, exact: true }).click();
  await page.getByTestId('download-1080p-btn').click();
  const exportPayload = (await exportRequest).postDataJSON() as {
    subtitle_position: number;
    subtitle_size: number;
  };
  expect(exportPayload.subtitle_position).toBe(finalPosition);
  expect(exportPayload.subtitle_size).toBe(finalSize);

  await expect(page.getByTestId('inline-subtitle-editor')).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test('intelligence entry stays hidden while the feature is disabled', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await expect(page.getByRole('tab', { name: el.tabIntelligence })).toHaveCount(0);
    await expect(page.getByText(el.viralVerifyFacts, { exact: true })).toHaveCount(0);
    await expect(page.getByText(el.viralGenerateMetadata, { exact: true })).toHaveCount(0);
    await expectNoHorizontalOverflow(page, '[data-testid="editor-sidebar"]');
  }
});

test('style controls stay responsive when reduced effects are active', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
    Object.defineProperty(navigator, 'hardwareConcurrency', {
      configurable: true,
      value: 2,
    });
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await page.getByRole('tab', { name: el.tabStyles }).click();
  await stabilizeUi(page);

  const measureControls = () => page.evaluate(() => {
    const bounds = (testId: string) => {
      const element = document.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
      if (!element) throw new Error(`Missing style control: ${testId}`);
      const rect = element.getBoundingClientRect();
      return {
        x: rect.x,
        y: rect.y,
        right: rect.right,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      };
    };

    return {
      size: bounds('style-size-control'),
      color: bounds('style-color-control'),
      lines: bounds('style-lines-control'),
    };
  });

  await page.setViewportSize(viewports.desktop);
  const desktop = await measureControls();
  expect(desktop.color.y).toBeGreaterThanOrEqual(desktop.size.bottom);
  expect(Math.abs(desktop.color.x - desktop.size.x)).toBeLessThanOrEqual(1);
  expect(desktop.lines.x).toBeGreaterThanOrEqual(desktop.size.right);
  expect(Math.abs(desktop.color.bottom - desktop.lines.bottom)).toBeLessThanOrEqual(2);

  await page.setViewportSize(viewports.mobile);
  // A loaded video can keep the previous desktop grid geometry for more than
  // two animation frames while Chromium applies the mobile media query. Wait
  // for the layout contract itself instead of racing that asynchronous reflow.
  await expect.poll(async () => {
    const mobile = await measureControls();
    return {
      colorAfterSize: mobile.color.y >= mobile.size.bottom,
      linesAfterColor: mobile.lines.y >= mobile.color.bottom,
    };
  }).toEqual({
    colorAfterSize: true,
    linesAfterColor: true,
  });
  await expectNoHorizontalOverflow(page, '[data-testid="editor-sidebar"]');
});

test('subtitle color presets stay inside their surface at every responsive width', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
  await page.getByRole('tab', { name: el.tabStyles }).click();
  await stabilizeUi(page);

  for (const viewport of [
    { width: 320, height: 568 },
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 948, height: 994 },
    viewports.desktop,
  ]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }));

    const metrics = await page.evaluate(() => {
      const surface = document.querySelector<HTMLElement>('.editor-style-color-surface');
      const options = document.querySelector<HTMLElement>('[data-testid="style-color-options"]');
      if (!surface || !options) throw new Error('Missing color controls');

      const surfaceRect = surface.getBoundingClientRect();
      const optionRect = options.getBoundingClientRect();
      const swatches = Array.from(options.querySelectorAll<HTMLElement>('.editor-style-color-swatch'))
        .map((swatch) => {
          const rect = swatch.getBoundingClientRect();
          return { left: rect.left, right: rect.right, width: rect.width };
        });

      return {
        surface: {
          left: surfaceRect.left,
          right: surfaceRect.right,
          scrollWidth: surface.scrollWidth,
          clientWidth: surface.clientWidth,
        },
        options: {
          left: optionRect.left,
          right: optionRect.right,
          scrollWidth: options.scrollWidth,
          clientWidth: options.clientWidth,
        },
        swatches,
      };
    });

    expect(metrics.surface.scrollWidth, `${viewport.width}px surface overflow`)
      .toBeLessThanOrEqual(metrics.surface.clientWidth + 1);
    expect(metrics.options.scrollWidth, `${viewport.width}px options overflow`)
      .toBeLessThanOrEqual(metrics.options.clientWidth + 1);
    expect(metrics.options.left, `${viewport.width}px options left containment`)
      .toBeGreaterThanOrEqual(metrics.surface.left);
    expect(metrics.options.right, `${viewport.width}px options right containment`)
      .toBeLessThanOrEqual(metrics.surface.right + 1);
    expect(metrics.swatches).toHaveLength(4);
    for (const swatch of metrics.swatches) {
      expect(swatch.left, `${viewport.width}px swatch left containment`)
        .toBeGreaterThanOrEqual(metrics.surface.left);
      expect(swatch.right, `${viewport.width}px swatch right containment`)
        .toBeLessThanOrEqual(metrics.surface.right + 1);
      expect(swatch.width, `${viewport.width}px swatch touch target`)
        .toBeGreaterThanOrEqual(40);
      expect(swatch.width, `${viewport.width}px swatch maximum width`)
        .toBeLessThanOrEqual(48);
    }
  }

  await expect(page.getByRole('radio', { name: el.colorPurple })).toBeVisible();
  await expect(page.getByRole('radio', { name: 'Λευκό' })).toHaveCount(0);
});

test('workflow labels stay aligned across upload, captions, and export', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });

  const workflow = page.getByLabel(el.workflowProgressLabel);
  const uploadStep = workflow.getByRole('button', { name: new RegExp(`${el.stepLabel.replace('{n}', '1')} ${el.stepUpload}`) });
  const captionsStep = workflow.getByRole('button', { name: new RegExp(`${el.stepLabel.replace('{n}', '2')} ${el.stepCaptions}`) });
  const exportStep = workflow.getByRole('button', { name: new RegExp(`${el.stepLabel.replace('{n}', '3')} ${el.stepExport}`) });

  await uploadStep.click();
  await expect(uploadStep).toHaveAttribute('aria-current', 'step');
  await expect(page.getByRole('heading', { name: el.inputVideoTitle })).toBeVisible();
  await expect(page.getByText('STEP 2', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Upload Video', { exact: true })).toHaveCount(0);

  const inputSummary = page.getByRole('button', { name: el.inputVideoSummaryToggle });
  const inputDetails = page.getByTestId('input-video-details');
  await expect(inputSummary).toHaveAttribute('aria-expanded', 'false');
  await expect(inputDetails).toHaveAttribute('aria-hidden', 'true');
  await expect(inputDetails).toHaveAttribute('inert', '');
  await inputSummary.click();
  await expect(inputSummary).toHaveAttribute('aria-expanded', 'true');
  await expect(inputDetails).toHaveAttribute('aria-hidden', 'false');
  await expect(inputDetails).not.toHaveAttribute('inert', '');

  await page.setViewportSize(viewports.mobile);
  await expectNoHorizontalOverflow(page);
  await expectNoHorizontalOverflow(page, '[data-testid="upload-section"]');
  await page.setViewportSize(viewports.desktop);

  await captionsStep.click();
  await expect(captionsStep).toHaveAttribute('aria-current', 'step');
  await expect(page.getByRole('heading', { name: el.inputVideoTitle })).toBeVisible();

  await exportStep.click();
  await expect(exportStep).toHaveAttribute('aria-current', 'step');
  await page.getByRole('tab', { name: el.tabStyles }).click();
  await expect(page.getByRole('slider', { name: el.sizeLabel })).toBeVisible();
  await expect(page.getByRole('heading', { name: el.customSettings })).toHaveCount(0);
});

test('mobile consent and footer stay compact, readable, and touch friendly', async ({ page }) => {
  await page.setViewportSize({ width: 430, height: 932 });
  await mockApi(page, { authenticated: false });
  await page.addInitScript(() => {
    localStorage.removeItem('cookie-consent');
  });
  await page.goto('/');
  const consent = page.getByRole('dialog', { name: el.cookieTitle });
  await expect(consent).toBeVisible();

  const consentMetrics = await consent.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const card = element.firstElementChild as HTMLElement | null;
    const buttons = Array.from(element.querySelectorAll('button')).map((button) => {
      const buttonRect = button.getBoundingClientRect();
      return { width: buttonRect.width, height: buttonRect.height };
    });
    return {
      height: rect.height,
      background: card ? getComputedStyle(card).backgroundColor : '',
      buttons,
    };
  });

  expect(consentMetrics.height).toBeLessThanOrEqual(180);
  expect(consentMetrics.background).toBe('rgb(255, 255, 255)');
  for (const button of consentMetrics.buttons) {
    expect(button.width).toBeGreaterThanOrEqual(44);
    expect(button.height).toBeGreaterThanOrEqual(44);
  }
  const publicHeaderActions = page.locator('.language-toggle, .guest-sign-in');
  await expect(publicHeaderActions).toHaveCount(2);
  for (let index = 0; index < await publicHeaderActions.count(); index += 1) {
    const box = await publicHeaderActions.nth(index).boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
    expect(box?.width).toBeGreaterThanOrEqual(44);
  }

  await page.getByRole('button', { name: el.cookieDecline }).click();
  const footer = page.locator('.studio-footer');
  await footer.scrollIntoViewIfNeeded();
  const footerMetrics = await footer.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const links = Array.from(element.querySelectorAll<HTMLAnchorElement>('a')).map((link) => {
      const linkRect = link.getBoundingClientRect();
      return { left: linkRect.left, right: linkRect.right };
    });
    return {
      direction: getComputedStyle(element).flexDirection,
      left: rect.left,
      right: rect.right,
      links,
    };
  });

  expect(footerMetrics.direction).toBe('column');
  for (const link of footerMetrics.links) {
    expect(link.left).toBeGreaterThanOrEqual(footerMetrics.left);
    expect(link.right).toBeLessThanOrEqual(footerMetrics.right);
  }
});

for (const [label, viewport] of Object.entries(viewports)) {
  test.describe(`${label} layouts`, () => {
    test.use({ viewport });

    test('login page layout stays contained', async ({ page }) => {
      await mockApi(page, { authenticated: false });
      await page.goto('/login');
      await page.getByRole('heading', { name: el.loginHeading }).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page.getByText(el.loginSubtitle)).toBeVisible();
      await expect(page.getByText(/Mock|€0/)).toHaveCount(0);
      if (viewport.width <= 640) {
        await expect(page.locator('.auth-promise')).toBeHidden();
      }
      if (viewport.width <= 800) {
        const headerActions = page.locator('.language-toggle, .guest-sign-in');
        for (let index = 0; index < await headerActions.count(); index += 1) {
          const box = await headerActions.nth(index).boundingBox();
          expect(box?.height).toBeGreaterThanOrEqual(44);
          expect(box?.width).toBeGreaterThanOrEqual(44);
        }
      }
    });

    // REGRESSION: legal navigation replaced the registration page and lost
    // fields already entered by the user.
    test('register page layout stays contained', async ({ page }) => {
      await mockApi(page, { authenticated: false });
      await page.goto('/register');
      await page.getByRole('heading', { name: el.registerTitle }).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page.getByText(el.registerSubtitle)).toBeVisible();
      const legalNotice = page.locator('#register-legal-notice');
      await expect(legalNotice).toBeVisible();
      const termsLink = legalNotice.getByRole('link', {
        name: el.registerLegalTermsLink,
      });
      const privacyLink = legalNotice.getByRole('link', {
        name: el.registerLegalPrivacyLink,
      });
      await expect(termsLink).toHaveAttribute('href', '/terms');
      await expect(termsLink).toHaveAttribute('target', '_blank');
      await expect(termsLink).toHaveAttribute('rel', 'noopener noreferrer');
      await expect(privacyLink).toHaveAttribute('href', '/privacy');
      await expect(privacyLink).toHaveAttribute('target', '_blank');
      await expect(privacyLink).toHaveAttribute('rel', 'noopener noreferrer');
      await expect(page.getByRole('button', { name: el.registerSubmit }))
        .toHaveAttribute('aria-describedby', 'register-legal-notice');
      await expect(page.getByText(/Mock|€0/)).toHaveCount(0);
      if (viewport.width <= 640) {
        await expect(page.locator('.auth-promise')).toBeHidden();
      }
    });

    test('legal pages stay readable and contained', async ({ page }) => {
      await page.addInitScript(() => {
        localStorage.setItem('cookie-consent', 'declined');
      });

      const legalPages: Array<{
        path: string;
        heading: string;
        sectionHeadings: string[];
        bodyText: string | RegExp;
        absentBodyText?: RegExp;
      }> = [
        {
          path: '/privacy',
          heading: el.privacyPageTitle,
          sectionHeadings: [el.privacyPaymentsTitle, el.privacyFinancialRetentionTitle],
          bodyText: el.privacyFinancialRetentionBody,
        },
        {
          path: '/terms',
          heading: el.termsPageTitle,
          sectionHeadings: [el.termsSellerTitle, el.termsPaidCreditsScopeTitle],
          bodyText: el.termsPaidCreditsScopeBody,
        },
      ];
      for (const legalPage of legalPages) {
        await page.goto(legalPage.path);
        await page.getByRole('heading', { name: legalPage.heading }).waitFor();
        await stabilizeUi(page);
        await expectNoHorizontalOverflow(page);
        await expect(page.getByRole('link', { name: el.brandHomeLabel })).toBeVisible();
        await expect(page.getByRole('button', { name: new RegExp(el.switchLanguage.split('{')[0]) })).toBeVisible();
        if (viewport.width <= 800) {
          const languageBox = await page.locator('.language-toggle').boundingBox();
          expect(languageBox?.height).toBeGreaterThanOrEqual(44);
          expect(languageBox?.width).toBeGreaterThanOrEqual(44);
        }
        for (const sectionHeading of legalPage.sectionHeadings) {
          await expect(page.getByRole('heading', { name: sectionHeading })).toBeVisible();
        }
        await expect(page.getByText(legalPage.bodyText)).toBeVisible();
        if (legalPage.absentBodyText) {
          await expect(page.getByText(legalPage.absentBodyText)).toHaveCount(0);
        }
      }
    });

    test('workspace renders upload area without overflow', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await waitForUploadWorkspace(page);
      const uploadSection = page.getByTestId('upload-section');
      await uploadSection.waitFor({ state: 'visible' });

      // Check that the upload area is visible regardless of whether it is
      // rendering the full dropzone or the compact restored-session view.
      await expect(uploadSection).toBeVisible();
      await expect(page.getByTestId('credits-balance')).toContainText('125');
      await expect(page.getByTestId('credits-coin-icon')).toBeVisible();
      await expect(page.getByTestId('app-env-badge')).toHaveCount(0);
      await expect(page.getByTestId('mock-mode-badge')).toHaveCount(0);
      await expect(page.getByTestId('engine-settings-toggle')).toHaveCount(0);
      await expect(page.getByText('Δες έτοιμο παράδειγμα')).toHaveCount(0);
      await expect(page.locator('.studio-nav').getByText(el.accountSettingsTitle)).toHaveCount(0);

      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, 'nav');
    });

    test('completed preview stays contained without overflow', async ({ page }) => {
      await mockApi(page);
      await page.addInitScript(() => {
        localStorage.setItem('lastActiveJobId', 'job-futurist');
      });
      await page.goto('/');

      await page.getByTestId('completed-editor').waitFor({ timeout: 30_000 });
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, 'main');
      await expect(page.getByText(el.subtitlesReady)).toHaveCount(0);
      await expect(page.getByTestId('completed-editor')).toBeVisible();
      await expect(page.getByRole('tab', { name: el.tabTranscript })).toBeVisible();
      await expect(page.getByRole('tab', { name: el.tabStyles })).toBeVisible();
      await expect(page.getByText('Mock Studio')).toHaveCount(0);
    });

    test('history section shows event cards neatly', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await waitForDashboardShell(page);
      await expect(
        page.getByRole('banner', { name: 'gsubs studio' })
          .getByRole('button', { name: el.historyTitle }),
      ).toHaveCount(0);
      await page.getByRole('button', { name: el.profileLabel }).click();
      await page.getByRole('button', { name: el.historyTitle }).click();
      await page.getByRole('heading', { name: el.historyTitle }).waitFor();
      await page.getByText(el.historyExpiry).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);

      // Check that the history section is properly laid out
      // The mock history data might not be loaded automatically, so just verify the section exists
      await expect(page.getByRole('heading', { name: el.historyTitle })).toBeVisible();
      await expect(page.getByText(el.historyExpiry)).toBeVisible();
      if (viewport.width <= 800) {
        const historyDialog = page.getByRole('dialog', { name: el.historyTitle });
        const selectionBox = await page.getByRole('button', { name: el.selectMode })
          .boundingBox();
        expect(selectionBox?.height).toBeGreaterThanOrEqual(44);
        expect(selectionBox?.width).toBeGreaterThanOrEqual(44);

        const historyDownload = historyDialog.getByRole('link', {
          name: new RegExp(`^${el.download} `),
        }).first();
        const historyView = historyDialog.getByRole('button', {
          name: new RegExp(`^${el.view} `),
        }).first();
        const historyDelete = historyDialog.getByRole('button', {
          name: new RegExp(`^${el.deleteJob} `),
        }).first();
        const itemActions = [historyDownload, historyView, historyDelete];
        for (let index = 0; index < itemActions.length; index += 1) {
          await expect(itemActions[index]).toBeVisible();
          const box = await itemActions[index].boundingBox();
          expect(box?.height, `history item action ${index} height`)
            .toBeGreaterThanOrEqual(44);
          expect(box?.width, `history item action ${index} width`)
            .toBeGreaterThanOrEqual(44);
        }
        const historyCard = historyView.locator('..').locator('..');
        const historyLayout = await historyCard.evaluate((element) => {
          const metadata = element.firstElementChild as HTMLElement;
          const actions = element.querySelector<HTMLElement>('.recent-job-actions')!;
          const metadataRect = metadata.getBoundingClientRect();
          const actionsRect = actions.getBoundingClientRect();
          return {
            metadataWidth: metadataRect.width,
            metadataBottom: metadataRect.bottom,
            actionsTop: actionsRect.top,
          };
        });
        expect(historyLayout.metadataWidth).toBeGreaterThanOrEqual(240);
        expect(historyLayout.actionsTop).toBeGreaterThanOrEqual(historyLayout.metadataBottom);

        await historyDelete.click();
        const confirmationActions = [
          historyDialog.getByRole('button', {
            name: new RegExp(`^${el.confirmDelete} `),
          }),
          historyDialog.getByRole('button', { name: el.cancel }),
        ];
        for (let index = 0; index < confirmationActions.length; index += 1) {
          await expect(confirmationActions[index]).toBeVisible();
          const box = await confirmationActions[index].boundingBox();
          expect(box?.height, `history confirmation action ${index} height`)
            .toBeGreaterThanOrEqual(44);
          expect(box?.width, `history confirmation action ${index} width`)
            .toBeGreaterThanOrEqual(44);
        }
      }
    });

    test('account settings modal keeps controls readable', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await waitForDashboardShell(page);

      // Wait for the account settings button to be rendered (after auth check) and click it
      await page.getByRole('button', { name: el.profileLabel }).click();

      // Wait for the modal heading (the modal title is the first one visible)
      const dialog = page.getByRole('dialog', { name: el.accountSettingsTitle });
      await dialog.waitFor({ timeout: 5000 });

      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(dialog.getByRole('button', { name: el.closeLabel })).toBeFocused();
      await expect(page.getByText(el.accountSettingsSubtitle)).toBeVisible();
      await expect(dialog.getByText(el.deleteAccountDescription)).toBeVisible();
      await dialog.getByRole('button', { name: el.deleteAccount }).click();
      await expect(dialog.getByText(el.deleteAccountConfirm)).toBeVisible();

      const closeButton = dialog.getByRole('button', { name: el.closeLabel });
      const closeBounds = await closeButton.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      });
      expect(closeBounds.width).toBeGreaterThanOrEqual(44);
      expect(closeBounds.height).toBeGreaterThanOrEqual(44);
      if (viewport.width <= 800) {
        const buttons = dialog.getByRole('button');
        for (let index = 0; index < await buttons.count(); index += 1) {
          const box = await buttons.nth(index).boundingBox();
          if (!box) continue;
          expect(box.height, `account dialog button ${index} height`)
            .toBeGreaterThanOrEqual(44);
          expect(box.width, `account dialog button ${index} width`)
            .toBeGreaterThanOrEqual(44);
        }
      }
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await expect(page.getByRole('button', { name: el.profileLabel })).toBeFocused();
    });
  });
}

test('unauthenticated users can open the upload workspace before login', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/');
  await waitForUploadWorkspace(page, { authenticated: false });

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId('upload-section')).toBeVisible();
  await expect(page.getByText(
    el.uploadDropFootnote
      .replace('{size}', '500')
      .replace('{duration}', '10:00'),
  )).toBeVisible();
  const signInLink = page.getByRole('link', { name: el.guestSignIn });
  await expect(signInLink).toBeVisible();
  await expect(signInLink).toHaveAttribute('href', '/login');
  await signInLink.click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('button', { name: el.profileLabel })).toHaveCount(0);
});

// REGRESSION: signing out while the account dialog was open left the header
// inert, making the newly rendered sign-in link impossible to click.
test('sign-in remains interactive after logout from the account dialog', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await waitForDashboardShell(page);

  await page.getByRole('button', { name: el.profileLabel }).click();
  const dialog = page.getByRole('dialog', { name: el.accountSettingsTitle });
  const logoutRequestPromise = page.waitForRequest((request) => (
    request.method() === 'POST' && request.url().endsWith('/auth/logout')
  ));
  await dialog.getByRole('button', { name: el.signOut }).click();
  const logoutRequest = await logoutRequestPromise;

  expect(logoutRequest.headers().authorization).toBe('Bearer test-token');
  await expect.poll(
    () => page.evaluate(() => localStorage.getItem('auth_token')),
  ).toBeNull();
  const signInLink = page.getByRole('link', { name: el.guestSignIn });
  await expect(signInLink).toBeVisible();
  await signInLink.click();
  await expect(page).toHaveURL(/\/login$/);
});
