import { expect, test } from "@playwright/test";
import el from "@/i18n/el.json";
import { mockApi, stabilizeUi } from "./mocks";
import { expectNoHorizontalOverflow, viewports } from "./support/uiTestSupport";

const transcription = [
  {
    start: 0,
    end: 2,
    text: "ΠΡΩΤΗ ΦΡΑΣΗ",
    words: [
      { start: 0, end: 1, text: "ΠΡΩΤΗ" },
      { start: 1, end: 2, text: "ΦΡΑΣΗ" },
    ],
  },
  {
    start: 2,
    end: 4,
    text: "ΔΕΥΤΕΡΗ ΦΡΑΣΗ",
    words: [
      { start: 2, end: 3, text: "ΔΕΥΤΕΡΗ" },
      { start: 3, end: 4, text: "ΦΡΑΣΗ" },
    ],
  },
  {
    start: 4,
    end: 6,
    text: "ΤΡΙΤΗ ΦΡΑΣΗ",
    words: [
      { start: 4, end: 5, text: "ΤΡΙΤΗ" },
      { start: 5, end: 6, text: "ΦΡΑΣΗ" },
    ],
  },
];

test("separate handles move all subtitles or only the active phrase", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize(viewports.desktop);
  await mockApi(page, { transcription });
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  const overlay = page.getByTestId("subtitle-overlay");
  const phone = page.getByTestId("editor-phone");
  const moveAllHandle = page.getByRole("slider", {
    name: el.subtitleDragAllHandleLabel,
  });
  const moveCueHandle = page.getByRole("slider", {
    name: el.subtitleDragHandleLabel,
  });
  const resizeHandle = page.getByRole("slider", {
    name: el.subtitleResizeHandleLabel,
  });

  await expect(moveAllHandle).toBeVisible();
  await expect(moveCueHandle).toBeVisible();
  await expect(moveCueHandle).toHaveText("1");
  await expect(page.getByRole("switch")).toHaveCount(0);
  await expect(overlay).toHaveAttribute("data-source-cue-index", "0");
  await expect(overlay).toHaveAttribute("data-position-mode", "shared");
  const initialPosition = Number(await overlay.getAttribute("data-position"));
  const initialSize = Number(await overlay.getAttribute("data-font-size"));

  await page.getByRole("button", { name: el.previewVideoToggle }).click();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video) => !(video as HTMLVideoElement).paused),
    )
    .toBe(true);
  await moveAllHandle.press("ArrowUp");
  const sharedMovedPosition = initialPosition + 1;
  await expect(overlay).toHaveAttribute(
    "data-position",
    String(sharedMovedPosition),
  );
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video) => !(video as HTMLVideoElement).paused),
    )
    .toBe(true);
  await expect(overlay).toHaveAttribute("data-source-cue-index", "1", {
    timeout: 5_000,
  });
  await expect(overlay).toHaveAttribute(
    "data-position",
    String(sharedMovedPosition),
  );

  const positionSaveRequest = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().endsWith("/videos/jobs/job-futurist/transcription"),
  );
  await moveCueHandle.hover();
  const moveBox = await moveCueHandle.boundingBox();
  expect(moveBox).not.toBeNull();
  const moveX = moveBox!.x + moveBox!.width / 2;
  const moveY = moveBox!.y + moveBox!.height / 2;
  await page.mouse.down();
  await page.mouse.move(moveX, moveY - 55, { steps: 5 });
  await page.mouse.up();

  const savedPayload = (await positionSaveRequest).postDataJSON() as {
    cues: Array<{ text: string; position?: number }>;
  };
  expect(savedPayload.cues).toHaveLength(3);
  expect(savedPayload.cues[0]).not.toHaveProperty("position");
  expect(savedPayload.cues[1].position).toBeGreaterThan(sharedMovedPosition);
  expect(savedPayload.cues[2]).not.toHaveProperty("position");
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video) => !(video as HTMLVideoElement).paused),
    )
    .toBe(true);
  await page.getByRole("button", { name: el.previewVideoToggle }).click();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video) => (video as HTMLVideoElement).paused),
    )
    .toBe(true);

  await expect(overlay).toHaveAttribute("data-position-mode", "custom");
  const customPosition = Number(await overlay.getAttribute("data-position"));
  expect(customPosition).toBe(savedPayload.cues[1].position);

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
  await expect
    .poll(async () => Number(await overlay.getAttribute("data-font-size")))
    .toBeGreaterThan(initialSize);

  const finalSize = Number(await overlay.getAttribute("data-font-size"));
  const exportRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/videos/jobs/job-futurist/export"),
  );
  await page
    .getByRole("button", { name: el.exportMenuButton, exact: true })
    .click();
  await page.getByTestId("download-1080p-btn").click();
  const exportPayload = (await exportRequest).postDataJSON() as {
    subtitle_position: number;
    subtitle_size: number;
  };
  expect(exportPayload.subtitle_position).toBe(sharedMovedPosition);
  expect(exportPayload.subtitle_size).toBe(finalSize);

  await expect(
    phone.getByRole("button", { name: el.subtitleResetPosition }),
  ).toHaveCount(0);
  const resetRequest = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().endsWith("/videos/jobs/job-futurist/transcription"),
  );
  await page
    .locator('.cue-item[data-active="true"]')
    .getByRole("button", { name: el.subtitleResetPosition })
    .click();
  const resetPayload = (await resetRequest).postDataJSON() as {
    cues: Array<{ position?: number }>;
  };
  expect(resetPayload.cues.every((cue) => cue.position === undefined)).toBe(
    true,
  );
  await expect(overlay).toHaveAttribute("data-position-mode", "shared");

  await page.setViewportSize(viewports.mobile);
  await stabilizeUi(page);
  const mobileCueHandleBox = await moveCueHandle.boundingBox();
  expect(mobileCueHandleBox).not.toBeNull();
  expect(mobileCueHandleBox?.height ?? 0).toBeGreaterThanOrEqual(44);
  expect(mobileCueHandleBox?.width ?? 0).toBeGreaterThanOrEqual(44);
  const mobileSaveRequest = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().endsWith("/videos/jobs/job-futurist/transcription"),
  );
  const mobileX = mobileCueHandleBox!.x + mobileCueHandleBox!.width / 2;
  const mobileY = mobileCueHandleBox!.y + mobileCueHandleBox!.height / 2;
  await moveCueHandle.dispatchEvent("pointerdown", {
    pointerId: 81,
    pointerType: "touch",
    isPrimary: true,
    button: 0,
    buttons: 1,
    clientX: mobileX,
    clientY: mobileY,
  });
  await overlay.dispatchEvent("pointermove", {
    pointerId: 81,
    pointerType: "touch",
    isPrimary: true,
    buttons: 1,
    clientX: mobileX,
    clientY: mobileY - 35,
  });
  await overlay.dispatchEvent("pointerup", {
    pointerId: 81,
    pointerType: "touch",
    isPrimary: true,
    button: 0,
    clientX: mobileX,
    clientY: mobileY - 35,
  });
  const mobilePayload = (await mobileSaveRequest).postDataJSON() as {
    cues: Array<{ position?: number }>;
  };
  expect(mobilePayload.cues[1]).toHaveProperty("position");

  const transcriptReset = page.locator("#cue-1").getByRole("button", {
    name: el.subtitleResetPosition,
  });
  await expect(transcriptReset).toBeVisible();
  const transcriptResetBox = await transcriptReset.boundingBox();
  expect(transcriptResetBox?.height ?? 0).toBeGreaterThanOrEqual(44);
  await expectNoHorizontalOverflow(page);
});
