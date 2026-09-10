import { test, expect } from "@playwright/test";

test.describe("project pipeline smoke", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("alex@acme.dev");
    await page.getByLabel(/password/i).fill("demo");
    await page.getByRole("button", { name: /log in/i }).click();
    await expect(page).toHaveURL(/\/workspace/);
  });

  test("opens a project requirements phase", async ({ page }) => {
    await page.goto("/projects");
    await expect(page.getByText(/NexusPay|Projects/i).first()).toBeVisible();
    await page.goto("/projects/p1/requirements");
    await expect(page).toHaveURL(/\/projects\/p1\/requirements/);
  });
});
