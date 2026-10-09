import { test, expect } from "@playwright/test";

test.describe("auth smoke", () => {
  test("landing exposes login and demo sign-in reaches workspace", async ({ page }) => {
    await page.goto("/");
    // A button, not a link: the landing page opens the login route with the
    // router rather than an anchor. This asked for a link and had been red since
    // the first commit, unnoticed because only the design review spec was ever
    // run.
    await expect(
      page.getByRole("button", { name: /log in|sign in|get started/i }).first(),
    ).toBeVisible();

    await page.goto("/login");
    await page.getByLabel(/email/i).fill("alex@acme.dev");
    await page.getByLabel(/password/i).fill("demo");
    await page.getByRole("button", { name: /log in/i }).click();
    await expect(page).toHaveURL(/\/workspace/);
  });
});
