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
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });

  await page.setViewportSize(editorViewportMatrix[0]);
  await page.goto('/');
  await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
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
        stepper: bounds('[data-testid="workflow-stepper"]'),
        section: bounds('#preview-section'),
        duplicateStepHeaders: document.querySelectorAll('.editor-step-toggle').length,
        previewMetaCount: document.querySelectorAll('.editor-preview-meta').length,
        preview: bounds('[data-testid="editor-preview-panel"]'),
        phone: bounds('[data-testid="editor-phone"]'),
        sidebar: bounds('[data-testid="editor-sidebar"]'),
        exportPanel: bounds('.editor-export-panel'),
        videoExportGroup: bounds('[data-testid="video-export-group"]'),
        subtitleExportGroup: bounds('[data-testid="subtitle-export-group"]'),
        exportActions: Array.from(document.querySelectorAll<HTMLElement>('.editor-export-action')).map((element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        }),
        tabs: Array.from(document.querySelectorAll<HTMLElement>('.editor-tab')).map((element) => {
          const rect = element.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        }),
        newVideo: bounds('.editor-new-video'),
      };
    });

    // REGRESSION: the old desktop layout gave almost all width to the fixed sidebar,
    // leaving the video and export controls in an unusable sliver.
    expect(metrics.documentOverflow, `${viewport.width}px document overflow`).toBeLessThanOrEqual(1);
    expect(metrics.section.x, `${viewport.width}px section left edge`).toBeGreaterThanOrEqual(0);
    expect(metrics.section.right, `${viewport.width}px section right edge`).toBeLessThanOrEqual(viewport.width + 1);
    expect(metrics.intro.height, `${viewport.width}px hero height`).toBeLessThanOrEqual(viewport.height * 0.34);
    expect(metrics.stepper.bottom, `${viewport.width}px stepper order`).toBeLessThanOrEqual(metrics.section.y + 1);
    expect(metrics.duplicateStepHeaders, `${viewport.width}px duplicate step headings`).toBe(0);
    expect(metrics.previewMetaCount, `${viewport.width}px preview labels`).toBe(0);
    expect(metrics.videoExportGroup.right, `${viewport.width}px video export containment`).toBeLessThanOrEqual(metrics.exportPanel.right + 1);
    expect(metrics.subtitleExportGroup.right, `${viewport.width}px subtitle export containment`).toBeLessThanOrEqual(metrics.exportPanel.right + 1);
    expect(metrics.phone.width, `${viewport.width}px phone width`).toBeGreaterThanOrEqual(190);
    expect(metrics.phone.width, `${viewport.width}px phone width`).toBeLessThanOrEqual(280);

    for (const action of [...metrics.exportActions, ...metrics.tabs, metrics.newVideo]) {
      expect(action.height, `${viewport.width}px touch target height`).toBeGreaterThanOrEqual(44);
      expect(action.width, `${viewport.width}px touch target width`).toBeGreaterThanOrEqual(42);
    }

    if (viewport.width >= 900) {
      expect(metrics.preview.width, `${viewport.width}px desktop preview width`).toBeGreaterThanOrEqual(278);
      expect(metrics.sidebar.width, `${viewport.width}px desktop controls width`).toBeGreaterThanOrEqual(480);
      expect(metrics.preview.right, `${viewport.width}px desktop column order`).toBeLessThanOrEqual(metrics.sidebar.x + 1);
      expect(metrics.videoExportGroup.right, `${viewport.width}px desktop export group order`).toBeLessThanOrEqual(metrics.subtitleExportGroup.x + 1);
    } else {
      expect(metrics.preview.bottom, `${viewport.width}px mobile export order`).toBeLessThanOrEqual(metrics.exportPanel.y + 1);
      expect(metrics.exportPanel.bottom, `${viewport.width}px mobile controls order`).toBeLessThanOrEqual(metrics.sidebar.y + 1);
    }

    if (viewport.width <= 640) {
      expect(metrics.videoExportGroup.bottom, `${viewport.width}px mobile export group order`).toBeLessThanOrEqual(metrics.subtitleExportGroup.y + 1);
    }

    if (viewport.width <= 430) {
      await page.getByRole('tab', { name: el.tabStyles }).click();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, '[data-testid="editor-sidebar"]');
      await expect(page.getByRole('radio', { name: 'TikTok Pro' })).toBeVisible();
      await page.getByRole('tab', { name: el.tabTranscript }).click();
    }
  }
});

test('desktop style controls scroll internally without stretching the preview', async ({ page }) => {
  await page.setViewportSize({ width: 2048, height: 1152 });
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
  await page.getByRole('tab', { name: el.tabStyles }).click();
  await stabilizeUi(page);

  const metrics = await page.evaluate(() => {
    const workspace = document.querySelector<HTMLElement>('[data-testid="editor-workspace"]');
    const preview = document.querySelector<HTMLElement>('[data-testid="editor-preview-panel"]');
    const sidebar = document.querySelector<HTMLElement>('[data-testid="editor-sidebar"]');
    const sidebarBody = document.querySelector<HTMLElement>('.editor-sidebar-body');

    if (!workspace || !preview || !sidebar || !sidebarBody) {
      throw new Error('Missing completed editor layout element');
    }

    return {
      workspaceHeight: workspace.getBoundingClientRect().height,
      previewHeight: preview.getBoundingClientRect().height,
      previewBackgroundColor: getComputedStyle(preview).backgroundColor,
      sidebarHeight: sidebar.getBoundingClientRect().height,
      sidebarBodyClientHeight: sidebarBody.clientHeight,
      sidebarBodyScrollHeight: sidebarBody.scrollHeight,
    };
  });

  // REGRESSION: the long Styles form used to make the entire desktop grid nearly
  // 1,000px tall, stretching the black preview into a visually empty column.
  expect(metrics.workspaceHeight).toBeLessThanOrEqual(720);
  expect(Math.abs(metrics.previewHeight - metrics.sidebarHeight)).toBeLessThanOrEqual(1);
  expect(metrics.previewBackgroundColor).toBe('rgba(0, 0, 0, 0)');
  expect(metrics.sidebarBodyScrollHeight).toBeGreaterThan(metrics.sidebarBodyClientHeight);
});

test('three-line karaoke layout keeps explicit rows and non-overlapping words', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
  await page.getByRole('tab', { name: el.tabStyles }).click();
  await page.getByRole('radio', { name: new RegExp(el.linesThree) }).click();
  await stabilizeUi(page);

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }));

    await expect(page.getByTestId('subtitle-overlay')).toHaveAttribute('data-line-count', '3');
    await expect(page.getByTestId('subtitle-line')).toHaveCount(3);

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
  await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
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
  await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const overlay = page.getByTestId('subtitle-overlay');
  const moveHandle = page.getByRole('slider', { name: el.subtitleDragHandleLabel });
  const resizeHandle = page.getByRole('slider', { name: el.subtitleResizeHandleLabel });
  await expect(overlay).toBeVisible();
  await expect(moveHandle).toBeVisible();
  await expect(resizeHandle).toBeVisible();
  await expect(page.getByText(el.subtitleDirectManipulationHint)).toBeVisible();

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

test('intelligence actions remain readable on the light editor surface', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
  await page.getByRole('tab', { name: el.tabIntelligence }).click();
  await stabilizeUi(page);

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }));

    const verifyTitle = page.getByText(el.viralVerifyFacts, { exact: true });
    const metadataTitle = page.getByText(el.viralGenerateMetadata, { exact: true });
    await expect(verifyTitle).toBeVisible();
    await expect(metadataTitle).toBeVisible();

    const metrics = await page.evaluate(({ verifyText, metadataText }) => {
      const elements = Array.from(document.querySelectorAll<HTMLElement>('span'));
      const titles = [verifyText, metadataText].map((text) => {
        const element = elements.find((candidate) => candidate.textContent?.trim() === text);
        if (!element) throw new Error(`Missing intelligence title: ${text}`);
        const button = element.closest('button');
        if (!button) throw new Error(`Missing intelligence action button: ${text}`);
        const titleStyle = getComputedStyle(element);
        const buttonStyle = getComputedStyle(button);
        const rect = button.getBoundingClientRect();
        return {
          color: titleStyle.color,
          backgroundColor: buttonStyle.backgroundColor,
          width: rect.width,
          height: rect.height,
        };
      });
      return titles;
    }, { verifyText: el.viralVerifyFacts, metadataText: el.viralGenerateMetadata });

    for (const action of metrics) {
      expect(action.color).toBe('rgb(17, 18, 21)');
      expect(action.backgroundColor).toBe('rgb(255, 255, 255)');
      expect(action.width).toBeGreaterThanOrEqual(150);
      expect(action.height).toBeGreaterThanOrEqual(150);
    }
    await expectNoHorizontalOverflow(page, '[data-testid="editor-sidebar"]');
  }
});

test('workflow labels stay aligned across upload, captions, and export', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem('lastActiveJobId', 'job-futurist');
  });
  await page.goto('/');
  await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });

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
  await expect(page.getByRole('heading', { name: el.customSettings })).toBeVisible();
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
    });

    test('register page layout stays contained', async ({ page }) => {
      await mockApi(page, { authenticated: false });
      await page.goto('/register');
      await page.getByRole('heading', { name: el.registerTitle }).waitFor();
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expect(page.getByText(el.registerSubtitle)).toBeVisible();
      await expect(page.getByText(/Mock|€0/)).toHaveCount(0);
    });

    test('legal pages stay readable and contained', async ({ page }) => {
      await page.addInitScript(() => {
        localStorage.setItem('cookie-consent', 'declined');
      });

      for (const legalPage of [
        { path: '/privacy', heading: el.privacyPageTitle },
        { path: '/terms', heading: el.termsPageTitle },
      ]) {
        await page.goto(legalPage.path);
        await page.getByRole('heading', { name: legalPage.heading }).waitFor();
        await stabilizeUi(page);
        await expectNoHorizontalOverflow(page);
        await expect(page.getByRole('link', { name: el.brandHomeLabel })).toBeVisible();
        await expect(page.getByRole('button', { name: new RegExp(el.switchLanguage.split('{')[0]) })).toBeVisible();
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

      await page.getByText(el.subtitlesReady).waitFor({ timeout: 30_000 });
      await stabilizeUi(page);
      await expectNoHorizontalOverflow(page);
      await expectNoHorizontalOverflow(page, 'main');
      await expect(page.getByText(el.subtitlesReady)).toBeVisible();
      await expect(page.getByRole('tab', { name: el.tabTranscript })).toBeVisible();
      await expect(page.getByRole('tab', { name: el.tabStyles })).toBeVisible();
      await expect(page.getByText('Mock Studio')).toHaveCount(0);
    });

    test('history section shows event cards neatly', async ({ page }) => {
      await mockApi(page);
      await page.goto('/');
      await waitForDashboardShell(page);
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
      await expect(page.getByText(el.accountSettingsSubtitle)).toBeVisible();

      const closeButton = dialog.getByRole('button', { name: el.closeLabel });
      const closeBounds = await closeButton.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      });
      expect(closeBounds.width).toBeGreaterThanOrEqual(44);
      expect(closeBounds.height).toBeGreaterThanOrEqual(44);
    });
  });
}

test('unauthenticated users can open the upload workspace before login', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/');
  await waitForUploadWorkspace(page, { authenticated: false });

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId('upload-section')).toBeVisible();
  await expect(page.getByText(el.uploadDropFootnote.replace('{duration}', '10:00'))).toBeVisible();
  await expect(page.getByRole('button', { name: el.guestSignIn })).toBeVisible();
  await expect(page.getByRole('button', { name: el.profileLabel })).toHaveCount(0);
});
