import { expect, test } from "@playwright/test";
import el from "@/i18n/el.json";
import { mockApi, stabilizeUi } from "./mocks";

test("player and subtitle manipulation stay clear across browser engines", async ({
  page,
}, testInfo) => {
  // This intentionally exhaustive media-interaction scenario includes a
  // bounded 30s editor wait plus browser stabilization and long-press input.
  // Keep its budget local instead of weakening the suite-wide timeout.
  test.setTimeout(60_000);

  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const phone = page.getByTestId("editor-phone");
  const video = phone.locator("video");
  const overlay = page.getByTestId("subtitle-overlay");
  const isTouchProject =
    testInfo.project.name === "android-chromium" ||
    testInfo.project.name === "ios-webkit";

  await expect(phone).toBeVisible();
  await expect(overlay).toBeVisible();
  expect(await video.getAttribute("controls")).toBeNull();
  await expect(page.getByTestId("editor-preview-controls")).toHaveCount(0);
  await expect(page.getByText(el.subtitlesReady, { exact: true })).toHaveCount(
    0,
  );
  await expect(page.locator(".subtitle-edit-affordance")).toHaveCount(0);

  if (testInfo.project.name === "ios-webkit") {
    // REGRESSION: a paused WebKit video with metadata-only preload stayed at
    // HAVE_METADATA and rendered a black phone until playback started.
    await expect
      .poll(async () =>
        video.evaluate((element) => (element as HTMLVideoElement).readyState),
      )
      .toBeGreaterThanOrEqual(2);
    await expect
      .poll(async () =>
        video.evaluate((element) => (element as HTMLVideoElement).currentTime),
      )
      .toBeGreaterThan(0);
  }

  const phoneBox = await phone.boundingBox();
  expect(phoneBox).not.toBeNull();
  expect(phoneBox!.width).toBeGreaterThanOrEqual(180);
  expect(phoneBox!.height).toBeGreaterThan(phoneBox!.width);

  const gestureY = phoneBox!.y + phoneBox!.height * 0.22;
  const gestureStartX = phoneBox!.x + phoneBox!.width * 0.35;
  await video.dispatchEvent("pointerdown", {
    bubbles: true,
    cancelable: true,
    pointerId: 31,
    pointerType: "touch",
    isPrimary: true,
    button: 0,
    clientX: gestureStartX,
    clientY: gestureY,
  });
  await video.dispatchEvent("pointermove", {
    bubbles: true,
    cancelable: true,
    pointerId: 31,
    pointerType: "touch",
    isPrimary: true,
    button: 0,
    clientX: gestureStartX + 48,
    clientY: gestureY + 1,
  });
  const seekFeedback = page.getByTestId("preview-gesture-feedback");
  await expect(seekFeedback).toBeVisible();
  await expect(seekFeedback).toContainText("/");
  await expect(seekFeedback).toContainText("−");
  await expect(page.getByTestId("preview-seek-progress")).toBeVisible();
  await video.dispatchEvent("pointerup", {
    bubbles: true,
    cancelable: true,
    pointerId: 31,
    pointerType: "touch",
    isPrimary: true,
    button: 0,
    clientX: gestureStartX + 48,
    clientY: gestureY + 1,
  });
  await expect(page.getByTestId("preview-gesture-feedback")).toHaveCount(0);

  if (isTouchProject) {
    // Exercise the real browser touch path. This catches transport bugs that
    // synthetic pointer dispatch and keyboard activation both bypass.
    await video.tap();
    await expect
      .poll(async () =>
        video.evaluate((element) => (element as HTMLVideoElement).paused),
      )
      .toBe(false);
    await video.tap();
    await expect
      .poll(async () =>
        video.evaluate((element) => (element as HTMLVideoElement).paused),
      )
      .toBe(true);
    await video.tap();
  } else {
    await video.press("Enter");
  }
  await expect
    .poll(async () =>
      video.evaluate((element) => (element as HTMLVideoElement).paused),
    )
    .toBe(false);

  await video.dispatchEvent("pointerdown", {
    bubbles: true,
    cancelable: true,
    pointerId: 32,
    pointerType: "touch",
    isPrimary: true,
    button: 0,
    clientX: gestureStartX,
    clientY: gestureY,
  });
  await page.waitForTimeout(550);
  await expect
    .poll(async () =>
      video.evaluate((element) => (element as HTMLVideoElement).playbackRate),
    )
    .toBe(2);
  await video.dispatchEvent("pointerup", {
    bubbles: true,
    cancelable: true,
    pointerId: 32,
    pointerType: "touch",
    isPrimary: true,
    button: 0,
    clientX: gestureStartX,
    clientY: gestureY,
  });
  await expect
    .poll(async () =>
      video.evaluate((element) => (element as HTMLVideoElement).playbackRate),
    )
    .toBe(1);

  if (isTouchProject) {
    // Keep the pinch assertion independent from each engine's media clock.
    // WebKit can advance beyond the short mocked cue while the long-press
    // assertions run, which correctly removes the overlay before we touch it.
    await video.evaluate((element) => {
      const media = element as HTMLVideoElement;
      media.pause();
      media.currentTime = 0.5;
      media.dispatchEvent(new Event("seeked"));
    });
    await expect(overlay).toBeVisible();
    await expect(page.getByTestId("subtitle-drag-handle")).toBeHidden();
    await expect(page.getByTestId("subtitle-resize-handle")).toBeHidden();
    await expect(
      page.getByTestId("subtitle-touch-manipulation-hint"),
    ).toHaveCount(0);
    await expect(phone.locator(".preview-gesture-surface")).toHaveCSS(
      "touch-action",
      "none",
    );

    const initialFontSize = Number(
      await overlay.getAttribute("data-font-size"),
    );
    const pinchStartTime = await video.evaluate(
      (element) => (element as HTMLVideoElement).currentTime,
    );
    const centerX = phoneBox!.x + phoneBox!.width / 2;
    const centerY = phoneBox!.y + phoneBox!.height / 2;
    let finishPinch: () => Promise<void>;

    if (testInfo.project.name === "android-chromium") {
      // CDP touch injection creates genuine active contacts, hit testing, and
      // pointer-capture transfer. Synthetic dispatchEvent cannot cover those.
      const overlayBox = await overlay.boundingBox();
      expect(overlayBox).not.toBeNull();
      const session = await page.context().newCDPSession(page);
      const touch = (id: number, x: number, y: number) => ({
        id,
        x,
        y,
        radiusX: 6,
        radiusY: 6,
        force: 1,
      });
      const firstTouch = touch(
        1,
        Math.max(phoneBox!.x + 4, overlayBox!.x - 12),
        overlayBox!.y + overlayBox!.height / 2,
      );
      const secondStart = touch(
        2,
        overlayBox!.x + overlayBox!.width / 2,
        overlayBox!.y + overlayBox!.height / 2,
      );
      const secondOutward = touch(
        2,
        Math.min(phoneBox!.x + phoneBox!.width - 4, secondStart.x + 40),
        secondStart.y,
      );
      const secondInward = touch(
        2,
        firstTouch.x + Math.max(20, (secondStart.x - firstTouch.x) * 0.45),
        secondStart.y,
      );

      await session.send("Input.dispatchTouchEvent", {
        type: "touchStart",
        touchPoints: [firstTouch],
      });
      await session.send("Input.dispatchTouchEvent", {
        type: "touchStart",
        touchPoints: [firstTouch, secondStart],
      });
      await page.waitForTimeout(550);
      await expect
        .poll(async () =>
          video.evaluate(
            (element) => (element as HTMLVideoElement).playbackRate,
          ),
        )
        .toBe(1);
      await session.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [firstTouch, secondOutward],
      });

      finishPinch = async () => {
        await session.send("Input.dispatchTouchEvent", {
          type: "touchEnd",
          touchPoints: [],
        });
        await session.detach();
      };

      await expect
        .poll(async () => Number(await overlay.getAttribute("data-font-size")))
        .toBeGreaterThan(initialFontSize);
      await session.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [firstTouch, secondInward],
      });
    } else {
      await video.dispatchEvent("pointerdown", {
        bubbles: true,
        cancelable: true,
        pointerId: 41,
        pointerType: "touch",
        isPrimary: true,
        clientX: centerX - 40,
        clientY: centerY,
      });
      await overlay.dispatchEvent("pointerdown", {
        bubbles: true,
        cancelable: true,
        pointerId: 42,
        pointerType: "touch",
        isPrimary: false,
        clientX: centerX + 40,
        clientY: centerY,
      });
      await page.waitForTimeout(550);
      await expect
        .poll(async () =>
          video.evaluate(
            (element) => (element as HTMLVideoElement).playbackRate,
          ),
        )
        .toBe(1);
      await overlay.dispatchEvent("pointermove", {
        bubbles: true,
        cancelable: true,
        pointerId: 42,
        pointerType: "touch",
        isPrimary: false,
        clientX: centerX + 60,
        clientY: centerY,
      });
      await expect
        .poll(async () => Number(await overlay.getAttribute("data-font-size")))
        .toBeGreaterThan(initialFontSize);
      await overlay.dispatchEvent("pointermove", {
        bubbles: true,
        cancelable: true,
        pointerId: 42,
        pointerType: "touch",
        isPrimary: false,
        clientX: centerX + 20,
        clientY: centerY,
      });

      finishPinch = async () => {
        await overlay.dispatchEvent("pointerup", {
          bubbles: true,
          cancelable: true,
          pointerId: 42,
          pointerType: "touch",
          isPrimary: false,
          clientX: centerX + 20,
          clientY: centerY,
        });
        await video.dispatchEvent("pointerup", {
          bubbles: true,
          cancelable: true,
          pointerId: 41,
          pointerType: "touch",
          isPrimary: true,
          clientX: centerX - 40,
          clientY: centerY,
        });
      };
    }

    await expect
      .poll(async () => Number(await overlay.getAttribute("data-font-size")))
      .toBeLessThan(initialFontSize);
    await expect(page.getByTestId("preview-gesture-feedback")).toHaveCount(0);
    await expect
      .poll(async () =>
        video.evaluate((element) => (element as HTMLVideoElement).currentTime),
      )
      .toBeCloseTo(pinchStartTime, 1);
    await finishPinch();

    if (testInfo.project.name === "android-chromium") {
      // The per-phrase scope switch belongs to the transcript row, so the
      // whole phone remains available to the real video touch path.
      const playbackTapY = gestureY;
      await page.touchscreen.tap(gestureStartX, playbackTapY);
      await expect
        .poll(async () =>
          video.evaluate((element) => (element as HTMLVideoElement).paused),
        )
        .toBe(false);
      await page.touchscreen.tap(gestureStartX, playbackTapY);
      await expect
        .poll(async () =>
          video.evaluate((element) => (element as HTMLVideoElement).paused),
        )
        .toBe(true);
    }

    await page.getByRole("tab", { name: el.tabStyles }).click();
    const workspace = page.getByTestId("editor-workspace");
    const previewPanel = page.getByTestId("editor-preview-panel");
    const sidebar = page.getByTestId("editor-sidebar");
    const sidebarBody = sidebar.locator(".editor-sidebar-body");
    const fixedHeader = page.locator(".studio-header");
    const readyActions = page.locator(".editor-ready-actions");

    await expect(workspace).toHaveClass(/editor-workspace-style-mode/);
    // REGRESSION: scrolling the style workspace directly placed the preceding
    // New Video / Export row underneath the fixed mobile header. Partial
    // visibility still satisfies Playwright's toBeVisible(), so compare the
    // rendered rectangles and require the entire action row to remain usable.
    await expect
      .poll(async () => {
        const headerBox = await fixedHeader.boundingBox();
        const actionsBox = await readyActions.boundingBox();
        if (!headerBox || !actionsBox) return -1;
        return actionsBox.y - (headerBox.y + headerBox.height);
      })
      .toBeGreaterThanOrEqual(0);
    await expect(previewPanel).toBeVisible();
    await expect(
      page.getByRole("slider", { name: el.sizeLabel }),
    ).toBeVisible();
    await expect(sidebar.getByRole("status")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: el.customSettings }),
    ).toHaveCount(0);

    const headerBox = await fixedHeader.boundingBox();
    const actionsBox = await readyActions.boundingBox();
    const newVideoBox = await page
      .getByRole("button", { name: el.newVideoButton })
      .boundingBox();
    const exportTriggerBox = await page
      .getByRole("button", {
        name: el.exportMenuButton,
        exact: true,
      })
      .boundingBox();
    const previewBox = await previewPanel.boundingBox();
    const stylePhoneBox = await phone.boundingBox();
    const sidebarBox = await sidebar.boundingBox();
    expect(headerBox).not.toBeNull();
    expect(actionsBox).not.toBeNull();
    expect(newVideoBox).not.toBeNull();
    expect(exportTriggerBox).not.toBeNull();
    expect(previewBox).not.toBeNull();
    expect(stylePhoneBox).not.toBeNull();
    expect(sidebarBox).not.toBeNull();
    expect(actionsBox!.y).toBeGreaterThanOrEqual(
      headerBox!.y + headerBox!.height,
    );
    expect(newVideoBox!.y).toBeGreaterThanOrEqual(
      headerBox!.y + headerBox!.height,
    );
    expect(exportTriggerBox!.y).toBeGreaterThanOrEqual(
      headerBox!.y + headerBox!.height,
    );
    expect(actionsBox!.y + actionsBox!.height).toBeLessThanOrEqual(
      page.viewportSize()!.height,
    );
    expect(stylePhoneBox!.width).toBeGreaterThanOrEqual(180);
    expect(sidebarBox!.y).toBeGreaterThanOrEqual(
      previewBox!.y + previewBox!.height,
    );
    await expect(page.getByTestId("editor-export-panel")).toHaveCount(0);

    // Mobile uses the page's natural scroll. The tab row must not float over
    // settings or create a second nested scroll surface.
    await expect
      .poll(async () =>
        sidebarBody.evaluate((element) => getComputedStyle(element).overflowY),
      )
      .toBe("visible");
    await expect
      .poll(async () =>
        sidebar
          .locator(".editor-tabs-sticky")
          .evaluate((element) => getComputedStyle(element).position),
      )
      .toBe("static");
    await sidebarBody.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await expect
      .poll(async () => sidebarBody.evaluate((element) => element.scrollTop))
      .toBe(0);
  } else {
    // Keep the desktop handle assertion tied to an active cue. Under a loaded
    // parallel suite the deliberately playing preview can otherwise advance
    // beyond the short fixture while earlier gesture assertions are running.
    await video.evaluate((element) => {
      const media = element as HTMLVideoElement;
      media.pause();
      media.currentTime = 0.5;
      media.dispatchEvent(new Event("seeked"));
    });
    await expect(overlay).toBeVisible();
    await expect(page.getByTestId("subtitle-drag-handle")).toBeVisible();
    await expect(page.getByTestId("subtitle-resize-handle")).toBeVisible();
  }

  await page
    .getByRole("button", { name: el.exportMenuButton, exact: true })
    .click();
  const exportMenu = page.getByTestId("editor-export-menu");
  await expect(exportMenu).toBeVisible();
  await expect(exportMenu.getByTestId("download-720p-btn")).toBeVisible();
  await expect(exportMenu.getByTestId("download-1080p-btn")).toBeVisible();
  await expect(exportMenu.getByTestId("download-4k-btn")).toBeVisible();
  await expect(exportMenu.getByTestId("srt-btn")).toBeVisible();
  await expect(exportMenu.getByTestId("txt-btn")).toBeVisible();
  await expect(exportMenu.getByTestId("vtt-btn")).toHaveCount(0);
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
  await page.keyboard.press("Escape");
  await expect(exportMenu).toHaveCount(0);

  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
});
