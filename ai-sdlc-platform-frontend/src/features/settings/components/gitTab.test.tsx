import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { connectionsApi, resetConnections } from "@/entities/settings/connections";
import { GitTab } from "./GitTab";

/**
 * The GitHub tab is not a sign in either. Its token is a password field with a
 * text field above it, the shape a password manager fills with a saved email
 * and password, as it did on the Atlas tab.
 */
afterEach(() => {
  cleanup();
  resetConnections();
});

describe("the GitHub tab", () => {
  it("does not invite a browser to fill in a sign in", async () => {
    await act(async () => {
      await connectionsApi.revoke("github");
    });
    const { container } = render(<GitTab />);

    const token = container.querySelector<HTMLInputElement>('input[type="password"]');
    expect(token?.getAttribute("autocomplete")).toBe("new-password");
    // The default organisation went: repositories land in the token owner's
    // account whatever it said, so nothing read it.
    expect(container.querySelector('input[placeholder="your-org"]')).toBeNull();
  });
});
