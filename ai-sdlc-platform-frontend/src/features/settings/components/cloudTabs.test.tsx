import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { connectionsApi, settingsApi } from "@/entities/settings";
import { resetConnections } from "@/entities/settings/connections";
import { DatabaseTab } from "./DatabaseTab";
import { RenderTab } from "./RenderTab";
import { VercelTab } from "./VercelTab";

/**
 * The Vercel and Render tabs ask only for the account: a token each, kept by
 * the credential store once as the GitHub token is, and where to make things.
 * Each project's own Vercel project and Render service are made by the platform,
 * so no field names one project, and there is no deploy hook to paste.
 */
afterEach(() => {
  cleanup();
  resetConnections();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function block(container: HTMLElement, provider: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`[data-connection="${provider}"]`);
  if (!found) throw new Error(`no ${provider} block`);
  return found;
}

describe("a provider secret", () => {
  it("goes to the credential store once, and the page keeps only the probe's verdict", async () => {
    const { container } = render(<RenderTab />);
    const key = within(block(container, "render")).getByLabelText(/^API key/);
    fireEvent.change(key, { target: { value: "rnd_not_a_real_key" } });

    await act(async () => {
      fireEvent.click(within(block(container, "render")).getByRole("button", { name: "Save" }));
    });

    const stored = block(container, "render");
    expect(within(stored).getByText(/^Works: /)).toBeTruthy();
    expect(within(stored).getByRole("button", { name: /check it again/i })).toBeTruthy();
    expect(within(stored).queryByLabelText(/^API key/)).toBeNull();
    expect(container.innerHTML).not.toContain("rnd_not_a_real_key");
  });

  it("offers no button that flips a connected flag the server refuses", () => {
    render(<VercelTab />);
    render(<RenderTab />);
    expect(screen.queryByRole("button", { name: /connect vercel/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /connect render/i })).toBeNull();
  });
});

describe("what the account keeps", () => {
  it("saves the team once the typing stops, not on every keystroke", async () => {
    vi.useFakeTimers();
    const update = vi.spyOn(settingsApi, "updateVercel");
    render(<VercelTab />);
    const field = screen.getByLabelText(/^Team \/ scope/);
    for (const typed of ["a", "ac", "acm", "acme"]) {
      fireEvent.change(field, { target: { value: typed } });
    }
    expect(update).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith({ team: "acme" });
  });

  it("asks for nothing that names one project, and for no deploy hook", () => {
    const vercel = render(<VercelTab />).container;
    const renderTab = render(<RenderTab />).container;
    for (const label of [
      /^Project ID/,
      /^Team or account ID/,
      /^Production address/,
      /^Service ID/,
      /^Service address/,
      /^Deploy hook/,
    ]) {
      expect(screen.queryByLabelText(label)).toBeNull();
    }
    // The account's own secrets, stored or still to give.
    expect(vercel.querySelector('[data-connection="vercel"]')).toBeTruthy();
    expect(renderTab.querySelector('[data-connection="render"]')).toBeTruthy();
  });
});

describe("the database", () => {
  it("asks for the account's Atlas project, cluster and service account, and no credential", () => {
    const { container } = render(<DatabaseTab />);
    expect(screen.getByLabelText(/^Atlas project ID/)).toBeTruthy();
    expect(screen.getByLabelText(/^Cluster/)).toBeTruthy();
    expect(screen.getByLabelText(/^Service account client ID/)).toBeTruthy();
    // The secret is a connection, stored once and never shown again.
    expect(container.querySelector('[data-connection="atlas"]')).toBeTruthy();
    for (const label of [/^Password/, /^Connection string/, /^Username/, /^Port/]) {
      expect(screen.queryByLabelText(label)).toBeNull();
    }
    // Nothing flips a connected flag the server derives.
    expect(screen.queryByRole("button", { name: /test & connect/i })).toBeNull();
  });

  it("does not invite a browser to fill in a sign in", () => {
    // A password manager took the tab for a login and put the saved email into
    // the client ID field, the text field just above the secret.
    const { container } = render(<DatabaseTab />);
    for (const label of [/^Atlas project ID/, /^Cluster/, /^Service account client ID/]) {
      expect(screen.getByLabelText(label).getAttribute("autocomplete")).toBe("off");
    }
    const secret = container.querySelector<HTMLInputElement>(
      '[data-connection="atlas"] input[type="password"]',
    );
    expect(secret?.getAttribute("autocomplete")).toBe("new-password");
  });

  it("saves the project id once the typing stops, as an Atlas setting", async () => {
    vi.useFakeTimers();
    const update = vi.spyOn(settingsApi, "updateDatabase");
    render(<DatabaseTab />);
    const field = screen.getByLabelText(/^Atlas project ID/);
    for (const typed of ["6", "66", "66f0"]) {
      fireEvent.change(field, { target: { value: typed } });
    }
    expect(update).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith({ provider: "mongodb_atlas", projectId: "66f0" });
  });
});

/**
 * Removing a stored credential was one click, though the dialog that asks
 * first was right there.
 */
describe("removing a stored credential", () => {
  it("asks first, and keeps it when the answer is no", async () => {
    const revoke = vi.spyOn(connectionsApi, "revoke");
    const { container } = render(<VercelTab />);
    const stored = block(container, "vercel");

    fireEvent.click(within(stored).getByRole("button", { name: "Remove" }));
    expect(revoke).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    expect(revoke).not.toHaveBeenCalled();

    fireEvent.click(within(stored).getByRole("button", { name: "Remove" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Remove the token" }));
    });
    expect(revoke).toHaveBeenCalledWith("vercel");
  });
});

describe("the Atlas secret saved right after an identifier", () => {
  it("is checked with the identifier just typed", async () => {
    const order: string[] = [];
    vi.spyOn(settingsApi, "updateDatabase").mockImplementation(async (patch) => {
      order.push(`identifier ${JSON.stringify(patch)}`);
      return settingsApi.get();
    });
    vi.spyOn(connectionsApi, "create").mockImplementation(async (provider) => {
      order.push(`secret ${provider}`);
      throw new Error("stop here");
    });
    resetConnections();
    await act(async () => {
      await connectionsApi.revoke("atlas");
    });
    const { container } = render(<DatabaseTab />);
    fireEvent.change(screen.getByLabelText(/^Cluster/), { target: { value: "Cluster1" } });
    const secret = within(block(container, "atlas")).getByLabelText(/^Service account secret/);
    fireEvent.change(secret, { target: { value: "not-a-real-secret" } });

    await act(async () => {
      fireEvent.click(within(block(container, "atlas")).getByRole("button", { name: "Save" }));
    });

    expect(order[0]).toContain("Cluster1");
    expect(order[1]).toBe("secret atlas");
  });
});
