import { expect, test } from "@playwright/test";
import { mockApi, stabilizeUi } from "./mocks";
import {
  editorViewportMatrix,
  expectNoHorizontalOverflow,
  verifyCompletedEditorViewport,
  viewports,
} from "./support/uiTestSupport";
import el from "@/i18n/el.json";

test("completed editor remains readable across the responsive viewport matrix", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });

  await page.setViewportSize(editorViewportMatrix[0]);
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });
  await stabilizeUi(page);

  for (const viewport of editorViewportMatrix) {
    await verifyCompletedEditorViewport(page, viewport);
  }
});

test("workflow labels stay aligned across upload, captions, and export", async ({
  page,
}) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("lastActiveJobId", "job-futurist");
  });
  await page.goto("/");
  await page.getByTestId("completed-editor").waitFor({ timeout: 30_000 });

  const workflow = page.getByLabel(el.workflowProgressLabel);
  const uploadStep = workflow.getByRole("button", {
    name: new RegExp(`${el.stepLabel.replace("{n}", "1")} ${el.stepUpload}`),
  });
  const captionsStep = workflow.getByRole("button", {
    name: new RegExp(`${el.stepLabel.replace("{n}", "2")} ${el.stepCaptions}`),
  });
  const exportStep = workflow.getByRole("button", {
    name: new RegExp(`${el.stepLabel.replace("{n}", "3")} ${el.stepExport}`),
  });

  await uploadStep.click();
  await expect(uploadStep).toHaveAttribute("aria-current", "step");
  await expect(
    page.getByRole("heading", { name: el.inputVideoTitle }),
  ).toBeVisible();
  await expect(page.getByText("STEP 2", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Upload Video", { exact: true })).toHaveCount(0);

  const inputSummary = page.getByRole("button", {
    name: el.inputVideoSummaryToggle,
  });
  const inputDetails = page.getByTestId("input-video-details");
  await expect(inputSummary).toHaveAttribute("aria-expanded", "false");
  await expect(inputDetails).toHaveAttribute("aria-hidden", "true");
  await expect(inputDetails).toHaveAttribute("inert", "");
  await inputSummary.click();
  await expect(inputSummary).toHaveAttribute("aria-expanded", "true");
  await expect(inputDetails).toHaveAttribute("aria-hidden", "false");
  await expect(inputDetails).not.toHaveAttribute("inert", "");

  await page.setViewportSize(viewports.mobile);
  await expectNoHorizontalOverflow(page);
  await expectNoHorizontalOverflow(page, '[data-testid="upload-section"]');
  await page.setViewportSize(viewports.desktop);

  await captionsStep.click();
  await expect(captionsStep).toHaveAttribute("aria-current", "step");
  await expect(
    page.getByRole("heading", { name: el.inputVideoTitle }),
  ).toBeVisible();

  await exportStep.click();
  await expect(exportStep).toHaveAttribute("aria-current", "step");
  await page.getByRole("tab", { name: el.tabStyles }).click();
  await expect(page.getByRole("slider", { name: el.sizeLabel })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: el.customSettings }),
  ).toHaveCount(0);
});
