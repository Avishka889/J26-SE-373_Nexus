import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SettingsGate } from "./SettingsGate";

/**
 * Nothing editable shows until the server's settings have arrived. A tab that
 * showed the store's defaults meanwhile showed empty fields that filled
 * themselves a second later, which read as fields clearing on their own.
 */
afterEach(cleanup);

const FIELD = <input aria-label="Cluster" defaultValue="Cluster0" />;

describe("the settings, before and after the server answers", () => {
  it("shows that it is reading them, and no field, until they arrive", () => {
    render(
      <SettingsGate load={{ loaded: false, error: null }} onRetry={() => {}}>
        {FIELD}
      </SettingsGate>,
    );
    expect(screen.getByRole("status").textContent).toContain(
      "Reading your settings",
    );
    expect(screen.queryByLabelText("Cluster")).toBeNull();
  });

  it("shows the fields once they have arrived", () => {
    render(
      <SettingsGate load={{ loaded: true, error: null }} onRetry={() => {}}>
        {FIELD}
      </SettingsGate>,
    );
    expect(screen.getByLabelText("Cluster")).toBeTruthy();
  });

  it("says when they could not be read, and asks again", () => {
    const retry = vi.fn();
    render(
      <SettingsGate
        load={{ loaded: false, error: "502 Bad Gateway" }}
        onRetry={retry}
      >
        {FIELD}
      </SettingsGate>,
    );
    expect(
      screen.getByText(/could not be read from the server \(502 Bad Gateway\)/),
    ).toBeTruthy();
    expect(screen.queryByLabelText("Cluster")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
