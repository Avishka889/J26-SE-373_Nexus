import { test, expect, type Page } from "@playwright/test";

/**
 * The Activity Log opens and lists its events.
 *
 * It crashed to "Something went wrong." on every visit: its store handed React
 * a new empty list on every read until the log arrived, and React, seeing the
 * snapshot change on each read, rendered until it gave up ("Maximum update
 * depth exceeded").
 */

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

test("the activity log opens and lists what happened", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  await page.goto("/projects/p1/traceability");

  await expect(page.getByRole("heading", { name: "Activity Log" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Test repair applied").first()).toBeVisible();
  await expect(page.getByText("Something went wrong")).toHaveCount(0);
  expect(errors).toEqual([]);
});
