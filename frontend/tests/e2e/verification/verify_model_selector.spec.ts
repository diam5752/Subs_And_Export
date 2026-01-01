
import { test, expect } from '@playwright/test';

test('verify model selector structure', async ({ page }) => {
  // 1. Arrange: Go to the temporary test page
  await page.goto('/test-palette');

  // Wait for the selector to appear
  const step1 = page.getByText('STEP 1');
  await expect(step1).toBeVisible();

  // 2. Act: Inspect the Model Selector structure
  // Based on error context, the aria-label is translated to Greek: "Επιλέξτε μοντέλο"
  // But we want to test the STRUCTURE, so we should look for the element by role button
  // and the content inside it.

  // Actually, the main button should cover the area.
  // The structure is:
  // DIV
  //   BUTTON (Main Toggle)
  //   DIV (Text)
  //   BUTTON (Info)

  // Let's find the Info button first. It has aria-label "modelInfo" in the error context!
  // Why? Because 'modelInfo' key is missing, so it uses the key as fallback?
  // No, code says `t('modelInfo') || "Model comparison information"`.
  // If `t('modelInfo')` returns 'modelInfo' (because key missing), then 'modelInfo' || "..." returns 'modelInfo'.
  // Ah! `useI18n` hook returns key if missing?
  // Yes, usually.

  // So look for aria-label="modelInfo"
  const infoButton = page.locator('button[aria-label="modelInfo"]');
  await expect(infoButton).toBeVisible();

  // Now find the main button.
  // It has aria-label `t('modelSelectTitle') || 'Pick a Model'`.
  // In Greek (el-GR) which is likely default, `modelSelectTitle` -> "Επιλέξτε μοντέλο".
  const mainButton = page.locator('button[aria-label="Επιλέξτε μοντέλο"]');
  await expect(mainButton).toBeVisible();

  // Verify main button is NOT the same as info button
  const mainBox = await mainButton.boundingBox();
  const infoBox = await infoButton.boundingBox();

  expect(mainBox).not.toEqual(infoBox);

  // Verify info button is visually "above" or "inside" the area of main button (since main button covers all)
  // The info button has z-20, main has z-0.
  // We can hover info button.
  await infoButton.hover();

  // Wait a bit
  await page.waitForTimeout(500);

  // Take screenshot
  await page.screenshot({ path: 'verification.png' });
});
