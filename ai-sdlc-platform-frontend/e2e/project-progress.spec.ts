import { test, expect, type Page } from "@playwright/test";

/**
 * The overall figure is the whole project's, in the header and the sidebar alike.
 *
 * Both showed the current phase's own progress, so a project waiting on its test
 * review read 100 under "Overall progress". NexusPay Banking is that project in
 * the demo: design and code approved, testing at its review, nothing deployed.
 */

test.use({ viewport: { width: 1440, height: 900 } });

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

test("the overall figure is the four phases' mean, each named when hovered", async ({ page }) => {
  await login(page);
  await page.goto("/projects/p1/requirements");

  const figure = page.getByText("Overall progress", { exact: true }).locator("..");
  await expect(figure).toContainText("70%", { timeout: 30_000 });
  await expect(figure).toHaveAttribute(
    "title",
    [
      "Requirements & Design: 100%",
      "Code Generation: 100%",
      "Testing & Security: 80%",
      "Deployment: 0%",
    ].join("\n"),
  );

  // The sidebar's figure is the same one.
  await expect(page.getByRole("button", { name: /NexusPay Banking/ })).toContainText("70%");
});
