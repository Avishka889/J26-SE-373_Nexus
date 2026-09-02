import { test, expect, type Page } from "@playwright/test";

/**
 * The upload path end to end, on fixtures and with no backend.
 *
 * A markdown file is read in the browser, which is what makes this runnable in
 * CI, and it exercises everything the PDF path does apart from the parser: the
 * chip, the composition, the preview and the submit.
 */

const SRS = `# Pharmacy SRS

3.1 The system shall allow a pharmacist to record a dispense.
3.2 Stock levels shall update within 2 seconds of a dispense.`;

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

test.describe("composer file upload", () => {
  // The composer sits behind auth. "/" is the signed out marketing page and
  // has no file input, so every test logs in first and lands on the
  // dedicated new-project screen, the same entry point the design review
  // spec's own project-creation test uses.
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto("/projects/new");
  });

  test("an attached document becomes the text that is analysed", async ({ page }) => {
    await page.setInputFiles('input[type="file"]', {
      name: "pharmacy-srs.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(SRS),
    });

    const chip = page.getByText("pharmacy-srs.md");
    await expect(chip).toBeVisible();

    // The count is the honest part: it says how much was actually read.
    const counts = page.getByRole("button", { name: /\d+ words/ });
    await expect(counts).toBeVisible();

    await counts.click();
    const preview = page.getByRole("dialog", { name: "What will be analysed" });
    await expect(preview).toContainText("record a dispense");
    await expect(preview).toContainText("within 2 seconds");
    // Provenance is annotation, never inside the string the model reads.
    await expect(preview.locator("pre")).not.toContainText("pharmacy-srs.md");
    // Scoped to the dialog, where the labelled close control lives. The
    // backdrop dismisses on click too, but it is aria-hidden and out of tab
    // order on purpose, so it has no role to match and this resolves to the
    // header button either way.
    await preview.getByRole("button", { name: "Close" }).click();

    await expect(preview).toBeHidden();
  });

  test("removing the chip removes its text", async ({ page }) => {
    await page.setInputFiles('input[type="file"]', {
      name: "pharmacy-srs.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(SRS),
    });
    await expect(page.getByText("pharmacy-srs.md")).toBeVisible();

    await page.getByRole("button", { name: "Remove pharmacy-srs.md" }).click();
    await expect(page.getByText("pharmacy-srs.md")).toBeHidden();
  });

  test("a file the browser cannot read says so and stays on screen", async ({ page }) => {
    await page.setInputFiles('input[type="file"]', {
      name: "budget.xlsx",
      mimeType: "application/vnd.ms-excel",
      buffer: Buffer.from("not a spreadsheet"),
    });

    await expect(page.getByText(/Cannot read \.xlsx files/)).toBeVisible();
    // A row entry, not a toast: the filename sits beside its own reason rather
    // than the reason appearing on its own and the file being forgotten.
    await expect(page.getByText("budget.xlsx")).toBeVisible();
  });
});
