import { expect, test } from "@playwright/test";
import { mockApi, stabilizeUi, waitForUploadWorkspace } from "./mocks";
import { expectNoHorizontalOverflow, viewports } from "./support/uiTestSupport";
import el from "@/i18n/el.json";

test("desktop preview stays fixed when switching between transcript and style", async ({
  page,
}) => {
  // REGRESSION: the taller transcript sidebar vertically centered the phone,
  // while the natural-height style sidebar moved it almost 100px upward.
  await page.setViewportSize(viewports.desktop);
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const readPreviewPosition = () =>
    page.evaluate(() => {
      const phone = document.querySelector<HTMLElement>(
        '[data-testid="editor-phone"]',
      );
      const workspace = document.querySelector<HTMLElement>(
        '[data-testid="editor-workspace"]',
      );
      if (!phone || !workspace)
        throw new Error("Missing editor preview geometry");
      return {
        phoneTop: phone.getBoundingClientRect().top,
        workspaceTop: workspace.getBoundingClientRect().top,
        scrollY: window.scrollY,
      };
    });

  const transcriptPosition = await readPreviewPosition();

  await page.getByRole("tab", { name: el.tabStyles }).click();
  await stabilizeUi(page);
  const stylePosition = await readPreviewPosition();
  expect(
    Math.abs(
      stylePosition.phoneTop -
        stylePosition.workspaceTop -
        (transcriptPosition.phoneTop - transcriptPosition.workspaceTop),
    ),
    `transcript=${JSON.stringify(transcriptPosition)} style=${JSON.stringify(stylePosition)}`,
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs(
      stylePosition.phoneTop +
        stylePosition.scrollY -
        (transcriptPosition.phoneTop + transcriptPosition.scrollY),
    ),
    `transcript=${JSON.stringify(transcriptPosition)} style=${JSON.stringify(stylePosition)}`,
  ).toBeLessThanOrEqual(1);

  await page.getByRole("tab", { name: el.tabTranscript }).click();
  await stabilizeUi(page);
  const restoredTranscriptPosition = await readPreviewPosition();
  expect(
    Math.abs(
      restoredTranscriptPosition.phoneTop -
        restoredTranscriptPosition.workspaceTop -
        (transcriptPosition.phoneTop - transcriptPosition.workspaceTop),
    ),
    `initial=${JSON.stringify(transcriptPosition)} restored=${JSON.stringify(restoredTranscriptPosition)}`,
  ).toBeLessThanOrEqual(1);
});

test("logo protects an active editor before returning to the home workspace", async ({
  page,
}) => {
  // REGRESSION: the logo behaved as an unconditional link and offered no safe
  // way to cancel when a project was already open.
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });

  const homeLink = page.getByRole("link", { name: el.brandHomeLabel });
  await homeLink.click();
  const dialog = page.getByRole("dialog", {
    name: el.homeNavigationModalTitle,
  });
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId("completed-editor")).toBeVisible();

  await dialog.getByRole("button", { name: el.homeNavigationCancel }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("completed-editor")).toBeVisible();

  await homeLink.click();
  await dialog.getByRole("button", { name: el.homeNavigationConfirm }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("completed-editor")).toHaveCount(0);
  await waitForUploadWorkspace(page);
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("lastActiveJobId")))
    .toBeNull();
});

test("desktop style controls use their natural height without an empty sidebar", async ({
  page,
}) => {
  await page.setViewportSize({ width: 2048, height: 1152 });
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await page.getByRole("tab", { name: el.tabStyles }).click();
  await stabilizeUi(page);

  const metrics = await page.evaluate(() => {
    const workspace = document.querySelector<HTMLElement>(
      '[data-testid="editor-workspace"]',
    );
    const preview = document.querySelector<HTMLElement>(
      '[data-testid="editor-preview-panel"]',
    );
    const sidebar = document.querySelector<HTMLElement>(
      '[data-testid="editor-sidebar"]',
    );
    const sidebarBody = document.querySelector<HTMLElement>(
      ".editor-sidebar-body",
    );
    const tabContent = document.querySelector<HTMLElement>(
      ".editor-tab-content",
    );

    if (!workspace || !preview || !sidebar || !sidebarBody || !tabContent) {
      throw new Error("Missing completed editor layout element");
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
      persistentExportPanels: document.querySelectorAll(
        '[data-testid="editor-export-panel"]',
      ).length,
    };
  });

  // REGRESSION: a fixed desktop workspace height stretched the short Styles
  // sidebar and left a large blank panel below its final control.
  expect(metrics.sidebarHeight).toBeLessThan(metrics.previewHeight);
  expect(metrics.workspaceHeight).toBeCloseTo(metrics.previewHeight, 0);
  expect(metrics.sidebarBottomGap).toBeLessThanOrEqual(20);
  expect(metrics.previewBackgroundColor).toBe("rgba(0, 0, 0, 0)");
  expect(metrics.sidebarBodyScrollHeight).toBeLessThanOrEqual(
    metrics.sidebarBodyClientHeight + 1,
  );
  expect(metrics.persistentExportPanels).toBe(0);
});

test("up-to-three-line karaoke layout keeps explicit rows and non-overlapping words", async ({
  page,
}) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await page.getByRole("tab", { name: el.tabStyles }).click();
  const threeLineMode = page.getByRole("radio", {
    name: new RegExp(el.linesThree),
  });
  await threeLineMode.click();
  await expect(threeLineMode).toBeChecked();
  await stabilizeUi(page);

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await page.evaluate(
      () =>
        new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        }),
    );

    const overlay = page.getByTestId("subtitle-overlay");
    const visibleLines = page.getByTestId("subtitle-line");
    await expect(visibleLines.first()).toBeVisible();
    const renderedLineCount = await visibleLines.count();

    // "Up to 3 Lines" is a maximum, not a request to pad shorter captions.
    // Real font metrics differ between macOS and the Linux CI runner, so this
    // fixture may correctly occupy either two or three explicit rows.
    expect(renderedLineCount).toBeGreaterThanOrEqual(1);
    expect(renderedLineCount).toBeLessThanOrEqual(3);
    await expect(overlay).toHaveAttribute(
      "data-line-count",
      String(renderedLineCount),
    );

    const metrics = await page.evaluate(() => {
      const lines = Array.from(
        document.querySelectorAll<HTMLElement>('[data-testid="subtitle-line"]'),
      );
      const words = Array.from(
        document.querySelectorAll<HTMLElement>('[data-testid="subtitle-word"]'),
      );

      const sameLineGaps = lines.flatMap((line) => {
        const lineWords = Array.from(
          line.querySelectorAll<HTMLElement>('[data-testid="subtitle-word"]'),
        );
        return lineWords.slice(1).map((word, index) => {
          const previous = lineWords[index].getBoundingClientRect();
          return word.getBoundingClientRect().left - previous.right;
        });
      });

      return {
        lineOverflow: Math.max(
          0,
          ...lines.map((line) => line.scrollWidth - line.clientWidth),
        ),
        minimumWordGap: Math.min(...sameLineGaps),
        transforms: words.map((word) => getComputedStyle(word).transform),
      };
    });

    expect(
      metrics.lineOverflow,
      `${viewport.width}px subtitle line overflow`,
    ).toBeLessThanOrEqual(1);
    expect(
      metrics.minimumWordGap,
      `${viewport.width}px karaoke word gap`,
    ).toBeGreaterThan(1);
    expect(metrics.transforms.every((transform) => transform === "none")).toBe(
      true,
    );
    await expectNoHorizontalOverflow(page);
  }

  const lineModes = [
    { name: el.lines1Word, expectedMaximum: 1 },
    { name: el.linesSingle, expectedMaximum: 1 },
    { name: el.linesDouble, expectedMaximum: 2 },
    { name: el.linesThree, expectedMaximum: 3 },
  ];

  for (const mode of lineModes) {
    await page.getByRole("radio", { name: new RegExp(mode.name) }).click();
    const visibleLines = page.getByTestId("subtitle-line");
    await expect(visibleLines.first()).toBeVisible();
    expect(await visibleLines.count(), mode.name).toBeLessThanOrEqual(
      mode.expectedMaximum,
    );
  }
});

test("the active subtitle can be corrected directly on the video at mobile and desktop sizes", async ({
  page,
}) => {
  await page.setViewportSize(viewports.mobile);
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const editTrigger = page.getByRole("button", {
    name: el.subtitleInlineEditAction,
  });
  await expect(editTrigger).toBeVisible();
  await editTrigger.click();

  const inlineEditor = page.getByTestId("inline-subtitle-editor");
  const textarea = page.getByRole("textbox", {
    name: el.subtitleInlineTextareaLabel,
  });
  await expect(inlineEditor).toBeVisible();
  await expect(textarea).toBeFocused();
  await expect(
    page.getByRole("textbox", { name: el.transcriptEdit }),
  ).not.toBeFocused();
  const focusedEditorBox = await inlineEditor.boundingBox();
  expect(focusedEditorBox).not.toBeNull();
  expect(focusedEditorBox!.y).toBeGreaterThanOrEqual(0);
  expect(focusedEditorBox!.y + focusedEditorBox!.height).toBeLessThanOrEqual(
    viewports.mobile.height + 1,
  );
  await textarea.fill("ΝΕΟΣ ΣΩΣΤΟΣ ΥΠΟΤΙΤΛΟΣ");

  // The transcript panel and the editor on the video share one draft state.
  await expect(
    page.getByRole("textbox", { name: el.transcriptEdit }),
  ).toHaveValue("ΝΕΟΣ ΣΩΣΤΟΣ ΥΠΟΤΙΤΛΟΣ");

  for (const viewport of [viewports.mobile, viewports.desktop]) {
    await page.setViewportSize(viewport);
    await stabilizeUi(page);

    const metrics = await page.evaluate(() => {
      const phone = document.querySelector<HTMLElement>(
        '[data-testid="editor-phone"]',
      );
      const editor = document.querySelector<HTMLElement>(
        '[data-testid="inline-subtitle-editor"]',
      );
      if (!phone || !editor)
        throw new Error("Missing inline subtitle editor surface");
      const phoneRect = phone.getBoundingClientRect();
      const editorRect = editor.getBoundingClientRect();
      const actions = Array.from(
        editor.querySelectorAll<HTMLElement>("button"),
      ).map((button) => {
        const rect = button.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      });
      return {
        phone: {
          left: phoneRect.left,
          top: phoneRect.top,
          right: phoneRect.right,
          bottom: phoneRect.bottom,
        },
        editor: {
          left: editorRect.left,
          top: editorRect.top,
          right: editorRect.right,
          bottom: editorRect.bottom,
        },
        actions,
      };
    });

    expect(
      metrics.editor.left,
      `${viewport.width}px editor left`,
    ).toBeGreaterThanOrEqual(metrics.phone.left - 1);
    expect(
      metrics.editor.top,
      `${viewport.width}px editor top`,
    ).toBeGreaterThanOrEqual(metrics.phone.top - 1);
    expect(
      metrics.editor.right,
      `${viewport.width}px editor right`,
    ).toBeLessThanOrEqual(metrics.phone.right + 1);
    expect(
      metrics.editor.bottom,
      `${viewport.width}px editor bottom`,
    ).toBeLessThanOrEqual(metrics.phone.bottom + 1);
    for (const action of metrics.actions) {
      expect(
        action.width,
        `${viewport.width}px inline action width`,
      ).toBeGreaterThanOrEqual(44);
      expect(
        action.height,
        `${viewport.width}px inline action height`,
      ).toBeGreaterThanOrEqual(44);
    }
    await expectNoHorizontalOverflow(page);
  }

  const updateRequest = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().endsWith("/videos/jobs/job-futurist/transcription"),
  );
  await textarea.press("Control+Enter");
  const request = await updateRequest;
  const payload = request.postDataJSON() as { cues: Array<{ text: string }> };
  expect(payload.cues[0].text).toBe("ΝΕΟΣ ΣΩΣΤΟΣ ΥΠΟΤΙΤΛΟΣ");

  await expect(inlineEditor).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: el.subtitleInlineEditAction }),
  ).toContainText("ΝΕΟΣ ΣΩΣΤΟΣ ΥΠΟΤΙΤΛΟΣ");
});

test("style controls stay responsive when reduced effects are active", async ({
  page,
}) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
    Object.defineProperty(navigator, "hardwareConcurrency", {
      configurable: true,
      value: 2,
    });
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await page.getByRole("tab", { name: el.tabStyles }).click();
  await stabilizeUi(page);

  const measureControls = () =>
    page.evaluate(() => {
      const bounds = (testId: string) => {
        const element = document.querySelector<HTMLElement>(
          `[data-testid="${testId}"]`,
        );
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
        size: bounds("style-size-control"),
        color: bounds("style-color-control"),
        lines: bounds("style-lines-control"),
      };
    });

  await page.setViewportSize(viewports.desktop);
  const desktop = await measureControls();
  expect(desktop.color.y).toBeGreaterThanOrEqual(desktop.size.bottom);
  expect(Math.abs(desktop.color.x - desktop.size.x)).toBeLessThanOrEqual(1);
  expect(desktop.lines.x).toBeGreaterThanOrEqual(desktop.size.right);
  expect(
    Math.abs(desktop.color.bottom - desktop.lines.bottom),
  ).toBeLessThanOrEqual(2);

  await page.setViewportSize(viewports.mobile);
  // A loaded video can keep the previous desktop grid geometry for more than
  // two animation frames while Chromium applies the mobile media query. Wait
  // for the layout contract itself instead of racing that asynchronous reflow.
  await expect
    .poll(async () => {
      const mobile = await measureControls();
      return {
        colorAfterSize: mobile.color.y >= mobile.size.bottom,
        linesAfterColor: mobile.lines.y >= mobile.color.bottom,
      };
    })
    .toEqual({
      colorAfterSize: true,
      linesAfterColor: true,
    });
  await expectNoHorizontalOverflow(page, '[data-testid="editor-sidebar"]');
});

test("subtitle color presets stay inside their surface at every responsive width", async ({
  page,
}) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await page.getByRole("tab", { name: el.tabStyles }).click();
  await stabilizeUi(page);

  for (const viewport of [
    { width: 320, height: 568 },
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 948, height: 994 },
    viewports.desktop,
  ]) {
    await page.setViewportSize(viewport);
    await page.evaluate(
      () =>
        new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        }),
    );

    const metrics = await page.evaluate(() => {
      const surface = document.querySelector<HTMLElement>(
        ".editor-style-color-surface",
      );
      const options = document.querySelector<HTMLElement>(
        '[data-testid="style-color-options"]',
      );
      if (!surface || !options) throw new Error("Missing color controls");

      const surfaceRect = surface.getBoundingClientRect();
      const optionRect = options.getBoundingClientRect();
      const swatches = Array.from(
        options.querySelectorAll<HTMLElement>(".editor-style-color-swatch"),
      ).map((swatch) => {
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

    expect(
      metrics.surface.scrollWidth,
      `${viewport.width}px surface overflow`,
    ).toBeLessThanOrEqual(metrics.surface.clientWidth + 1);
    expect(
      metrics.options.scrollWidth,
      `${viewport.width}px options overflow`,
    ).toBeLessThanOrEqual(metrics.options.clientWidth + 1);
    expect(
      metrics.options.left,
      `${viewport.width}px options left containment`,
    ).toBeGreaterThanOrEqual(metrics.surface.left);
    expect(
      metrics.options.right,
      `${viewport.width}px options right containment`,
    ).toBeLessThanOrEqual(metrics.surface.right + 1);
    expect(metrics.swatches).toHaveLength(4);
    for (const swatch of metrics.swatches) {
      expect(
        swatch.left,
        `${viewport.width}px swatch left containment`,
      ).toBeGreaterThanOrEqual(metrics.surface.left);
      expect(
        swatch.right,
        `${viewport.width}px swatch right containment`,
      ).toBeLessThanOrEqual(metrics.surface.right + 1);
      expect(
        swatch.width,
        `${viewport.width}px swatch touch target`,
      ).toBeGreaterThanOrEqual(40);
      expect(
        swatch.width,
        `${viewport.width}px swatch maximum width`,
      ).toBeLessThanOrEqual(48);
    }
  }

  await expect(page.getByRole("radio", { name: el.colorPurple })).toBeVisible();
  await expect(page.getByRole("radio", { name: "Λευκό" })).toHaveCount(0);
});
