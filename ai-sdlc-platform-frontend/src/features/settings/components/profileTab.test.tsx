import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { settingsApi } from "@/entities/settings";
import { ProfileTab } from "./ProfileTab";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

/**
 * The name saved on every keystroke and the store took the answer back, so
 * typed characters dropped (twelve "Updated profile settings: name" rows in
 * eight seconds), and "Save changes" only showed a toast.
 */
describe("the profile", () => {
  it("saves a name once the typing stops, with everything typed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const update = vi.spyOn(settingsApi, "updateProfile");
    render(<ProfileTab />);
    const field = screen.getByLabelText(/^Full name/) as HTMLInputElement;

    for (const typed of ["A", "Ad", "Ada", "Ada ", "Ada L"]) {
      fireEvent.change(field, { target: { value: typed } });
    }
    expect(update).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith({ name: "Ada L" });
  });

  it("offers no button that only says it saved", () => {
    render(<ProfileTab />);

    expect(screen.queryByRole("button", { name: /save changes/i })).toBeNull();
  });
});
