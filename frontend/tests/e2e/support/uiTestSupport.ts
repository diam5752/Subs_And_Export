import { expect, type Page } from "@playwright/test";
import el from "@/i18n/el.json";
import { stabilizeUi } from "../mocks";

export const viewports = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
} as const;

export const editorViewportMatrix = [
  { width: 320, height: 568 },
  { width: 375, height: 667 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

export async function expectNoHorizontalOverflow(
  page: Page,
  selector?: string,
) {
  const overflow = await page.evaluate((sel) => {
    const target = sel
      ? document.querySelector<HTMLElement>(sel)
      : document.documentElement;
    if (!target) return 0;
    const clientWidth = target.clientWidth || window.innerWidth;
    return target.scrollWidth - clientWidth;
  }, selector);
  expect(overflow).toBeLessThanOrEqual(1);
}

type EditorViewport = (typeof editorViewportMatrix)[number];
type ElementSize = { width: number; height: number };

async function settleResponsiveLayout(page: Page) {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

async function readEditorMetrics(page: Page) {
  return page.evaluate(() => {
    const bounds = (selector: string) => {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) {
        throw new Error(`Missing responsive editor element: ${selector}`);
      }
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
    const subtitleTouchSurface = () => {
      const trigger = document.querySelector<HTMLElement>(
        ".subtitle-inline-trigger",
      );
      if (!trigger) return null;
      const pseudo = getComputedStyle(trigger, "::before");
      return {
        content: pseudo.content,
        top: pseudo.top,
        left: pseudo.left,
      };
    };

    return {
      documentOverflow:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      intro: bounds('[data-testid="studio-intro"]'),
      introDisplay: getComputedStyle(
        document.querySelector<HTMLElement>('[data-testid="studio-intro"]')!,
      ).display,
      stepper: bounds('[data-testid="workflow-stepper"]'),
      stepperDisplay: getComputedStyle(
        document.querySelector<HTMLElement>(
          '[data-testid="workflow-stepper"]',
        )!,
      ).display,
      section: bounds("#preview-section"),
      duplicateStepHeaders: document.querySelectorAll(".editor-step-toggle")
        .length,
      previewMetaCount: document.querySelectorAll(".editor-preview-meta")
        .length,
      preview: bounds('[data-testid="editor-preview-panel"]'),
      phone: bounds('[data-testid="editor-phone"]'),
      positionScope: bounds(".subtitle-position-scope-toggle"),
      positionScopeInsidePhone: Boolean(
        document
          .querySelector<HTMLElement>('[data-testid="editor-phone"]')
          ?.contains(
            document.querySelector<HTMLElement>(
              ".subtitle-position-scope-toggle",
            ) ?? null,
          ),
      ),
      sidebar: bounds('[data-testid="editor-sidebar"]'),
      tabsSticky: bounds(".editor-tabs-sticky"),
      transcriptList: bounds(".editor-transcript-list"),
      firstCueIdCount: document.querySelectorAll("#cue-0").length,
      tabs: Array.from(
        document.querySelectorAll<HTMLElement>(".editor-tab"),
      ).map((element) => {
        const rect = element.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      }),
      actionBar: bounds(".editor-ready-actions"),
      newVideo: bounds(".editor-new-video"),
      exportTrigger: bounds(".editor-export-trigger"),
      persistentExportPanels: document.querySelectorAll(".editor-export-panel")
        .length,
      headerActions: [
        bounds(".language-toggle"),
        bounds(".studio-credit-balance"),
        bounds(".profile-trigger"),
      ],
      cueActions: Array.from(
        document.querySelectorAll<HTMLElement>(
          ".cue-time-button, .cue-text-button, .cue-edit-button",
        ),
      ).map((element) => {
        const rect = element.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      }),
      subtitleTouchSurface: subtitleTouchSurface(),
    };
  });
}

type EditorMetrics = Awaited<ReturnType<typeof readEditorMetrics>>;

function expectTouchTargets(
  actions: readonly ElementSize[],
  viewportWidth: number,
  label: string,
) {
  for (const action of actions) {
    expect(
      action.height,
      `${viewportWidth}px ${label} height`,
    ).toBeGreaterThanOrEqual(44);
    expect(
      action.width,
      `${viewportWidth}px ${label} width`,
    ).toBeGreaterThanOrEqual(42);
  }
}

function expectBaseEditorMetrics(
  metrics: EditorMetrics,
  viewport: EditorViewport,
) {
  expect(
    metrics.documentOverflow,
    `${viewport.width}px document overflow`,
  ).toBeLessThanOrEqual(1);
  expect(
    metrics.section.x,
    `${viewport.width}px section left edge`,
  ).toBeGreaterThanOrEqual(0);
  expect(
    metrics.section.right,
    `${viewport.width}px section right edge`,
  ).toBeLessThanOrEqual(viewport.width + 1);
  expect(
    metrics.introDisplay,
    `${viewport.width}px completed workspace hero`,
  ).toBe("none");
  expect(
    metrics.intro.height,
    `${viewport.width}px completed workspace hero height`,
  ).toBe(0);
  expect(
    metrics.duplicateStepHeaders,
    `${viewport.width}px duplicate step headings`,
  ).toBe(0);
  expect(metrics.previewMetaCount, `${viewport.width}px preview labels`).toBe(
    0,
  );
  expect(
    metrics.persistentExportPanels,
    `${viewport.width}px persistent export panels`,
  ).toBe(0);
  expect(
    metrics.phone.width,
    `${viewport.width}px phone width`,
  ).toBeGreaterThanOrEqual(
    viewport.width <= 640 && viewport.height <= 700 ? 160 : 190,
  );
  expect(
    metrics.phone.width,
    `${viewport.width}px phone width`,
  ).toBeLessThanOrEqual(280);
  expect(
    metrics.positionScopeInsidePhone,
    `${viewport.width}px scope toggle placement`,
  ).toBe(true);
  expect(
    metrics.positionScope.height,
    `${viewport.width}px scope toggle touch target`,
  ).toBeGreaterThanOrEqual(44);
  expect(
    metrics.positionScope.x,
    `${viewport.width}px scope toggle left containment`,
  ).toBeGreaterThanOrEqual(metrics.phone.x - 1);
  expect(
    metrics.positionScope.right,
    `${viewport.width}px scope toggle right containment`,
  ).toBeLessThanOrEqual(metrics.phone.right + 1);
  expect(
    metrics.transcriptList.y,
    `${viewport.width}px transcript below sticky tabs`,
  ).toBeGreaterThanOrEqual(metrics.tabsSticky.bottom - 1);
  expect(
    metrics.firstCueIdCount,
    `${viewport.width}px unique first cue id`,
  ).toBe(1);
  expect(
    metrics.newVideo.x,
    `${viewport.width}px new video left alignment`,
  ).toBeLessThan(metrics.exportTrigger.x);
  expect(
    metrics.newVideo.x,
    `${viewport.width}px new video action containment`,
  ).toBeGreaterThanOrEqual(metrics.actionBar.x);
  expect(
    metrics.exportTrigger.right,
    `${viewport.width}px export action containment`,
  ).toBeLessThanOrEqual(metrics.actionBar.right + 1);
  expectTouchTargets(
    [...metrics.tabs, metrics.newVideo, metrics.exportTrigger],
    viewport.width,
    "touch target",
  );
}

function expectMobileEditorMetrics(
  metrics: EditorMetrics,
  viewport: EditorViewport,
) {
  expectTouchTargets(
    metrics.headerActions,
    viewport.width,
    "mobile header touch target",
  );
  expectTouchTargets(metrics.cueActions, viewport.width, "cue touch target");
  expect(
    metrics.subtitleTouchSurface,
    `${viewport.width}px subtitle touch surface`,
  ).toEqual(
    expect.objectContaining({
      content: '""',
      top: "-16px",
      left: "-12px",
    }),
  );
}

function expectResponsiveColumns(
  metrics: EditorMetrics,
  viewport: EditorViewport,
) {
  if (viewport.width >= 900) {
    expect(
      metrics.stepperDisplay,
      `${viewport.width}px desktop workflow breadcrumb`,
    ).not.toBe("none");
    expect(
      metrics.stepper.bottom,
      `${viewport.width}px stepper order`,
    ).toBeLessThanOrEqual(metrics.section.y + 1);
    expect(
      metrics.preview.width,
      `${viewport.width}px desktop preview width`,
    ).toBeGreaterThanOrEqual(278);
    expect(
      metrics.sidebar.width,
      `${viewport.width}px desktop controls width`,
    ).toBeGreaterThanOrEqual(480);
    expect(
      metrics.preview.right,
      `${viewport.width}px desktop column order`,
    ).toBeLessThanOrEqual(metrics.sidebar.x + 1);
    return;
  }

  if (viewport.width <= 640) {
    expect(
      metrics.stepperDisplay,
      `${viewport.width}px compact mobile workspace`,
    ).toBe("none");
  } else {
    expect(
      metrics.stepperDisplay,
      `${viewport.width}px tablet workflow breadcrumb`,
    ).not.toBe("none");
  }
  expect(
    metrics.preview.bottom,
    `${viewport.width}px mobile preview order`,
  ).toBeLessThanOrEqual(metrics.sidebar.y + 1);
  expect(
    metrics.tabsSticky.y,
    `${viewport.width}px editor tabs visible in first viewport`,
  ).toBeLessThan(viewport.height);
}

async function expectResponsiveExportMenu(
  page: Page,
  viewport: EditorViewport,
) {
  await page
    .getByRole("button", { name: el.exportMenuButton, exact: true })
    .click();
  const exportMenu = page.getByTestId("editor-export-menu");
  await expect(exportMenu).toBeVisible();
  const metrics = await exportMenu.evaluate((menu) => {
    const menuRect = menu.getBoundingClientRect();
    const actions = Array.from(
      menu.querySelectorAll<HTMLElement>(".editor-export-action"),
    ).map((element) => {
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
  expect(
    metrics.left,
    `${viewport.width}px export menu left containment`,
  ).toBeGreaterThanOrEqual(0);
  expect(
    metrics.right,
    `${viewport.width}px export menu right containment`,
  ).toBeLessThanOrEqual(viewport.width + 1);
  expect(
    metrics.top,
    `${viewport.width}px export menu top containment`,
  ).toBeGreaterThanOrEqual(0);
  expect(
    metrics.bottom,
    `${viewport.width}px export menu bottom containment`,
  ).toBeLessThanOrEqual(viewport.height + 1);
  expect(metrics.vttOptions, `${viewport.width}px public VTT option`).toBe(0);
  expect(metrics.actions).toHaveLength(5);
  expectTouchTargets(metrics.actions, viewport.width, "export touch target");
  await page.keyboard.press("Escape");
  await expect(exportMenu).toHaveCount(0);
}

async function expectCompactStyleControls(page: Page) {
  await page.getByRole("tab", { name: el.tabStyles }).click();
  await stabilizeUi(page);
  await expectNoHorizontalOverflow(page);
  await expectNoHorizontalOverflow(page, '[data-testid="editor-sidebar"]');
  await expect(page.getByRole("slider", { name: el.sizeLabel })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: el.customSettings }),
  ).toHaveCount(0);
  for (const removedPreset of [
    "TikTok Pro",
    "Cinematic Master",
    "Podcast Style",
    "Τελευταία Χρήση",
  ]) {
    await expect(page.getByText(removedPreset, { exact: true })).toHaveCount(0);
  }
  await page.getByRole("tab", { name: el.tabTranscript }).click();
}

export async function verifyCompletedEditorViewport(
  page: Page,
  viewport: EditorViewport,
) {
  await page.setViewportSize(viewport);
  await settleResponsiveLayout(page);
  const metrics = await readEditorMetrics(page);

  expectBaseEditorMetrics(metrics, viewport);
  if (viewport.width <= 800) expectMobileEditorMetrics(metrics, viewport);
  expectResponsiveColumns(metrics, viewport);
  await expectResponsiveExportMenu(page, viewport);
  if (viewport.width <= 430) await expectCompactStyleControls(page);
}
