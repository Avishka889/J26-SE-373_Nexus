import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/**
 * A public page paints at once.
 *
 * Every route used to wait behind a boot screen for the owner's whole project
 * list, so a visitor to the landing page watched a spinner for six seconds
 * while a list they had no business downloading came down.
 */
describe("the app's providers", () => {
  it("render the page without waiting for the server", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    const { AppProviders } = await import("./providers");

    render(
      <AppProviders>
        <p>The landing page</p>
      </AppProviders>,
    );

    expect(screen.getByText("The landing page")).toBeTruthy();
  });
});
