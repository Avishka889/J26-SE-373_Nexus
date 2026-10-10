import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useId, useState } from "react";
import { Select, type SelectOption } from "./Select";

afterEach(cleanup);

const TARGETS: SelectOption[] = [
  { value: "local", label: "This machine" },
  { value: "cloud", label: "Vercel and Render", note: "No Render connection: add one in Settings.", disabled: true },
  { value: "preview", label: "Preview only" },
];

function Harness({ onChange = () => undefined, disabled = false }: { onChange?: (v: string) => void; disabled?: boolean }) {
  const id = useId();
  const [value, setValue] = useState("local");
  return (
    <>
      <label htmlFor={id}>Release to</label>
      <Select
        id={id}
        value={value}
        options={TARGETS}
        disabled={disabled}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
      />
    </>
  );
}

const trigger = () => screen.getByRole("combobox", { name: "Release to" });

/**
 * The dropdowns were the browser's own, whose open list no style reaches and
 * whose options hold one line of text.
 */
describe("the platform's dropdown", () => {
  it("is named by its label, shows what is chosen, and is closed", () => {
    render(<Harness />);

    expect(trigger().textContent).toBe("This machine");
    expect(trigger().getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("opens its options, marks the chosen one, and takes a choice", async () => {
    const chosen = vi.fn();
    render(<Harness onChange={chosen} />);
    await userEvent.click(trigger());

    const list = await screen.findByRole("listbox");
    expect(within(list).getAllByRole("option").map((o) => o.getAttribute("aria-selected"))).toEqual([
      "true",
      "false",
      "false",
    ]);
    await userEvent.click(within(list).getByRole("option", { name: /Preview only/ }));

    expect(chosen).toHaveBeenCalledWith("preview");
    expect(trigger().textContent).toBe("Preview only");
  });

  it("says in the list why an option cannot be chosen, and does not choose it", async () => {
    const chosen = vi.fn();
    render(<Harness onChange={chosen} />);
    await userEvent.click(trigger());

    const blocked = await screen.findByRole("option", { name: /Vercel and Render/ });
    expect(blocked.getAttribute("aria-disabled")).toBe("true");
    expect(blocked.textContent).toContain("No Render connection: add one in Settings.");
    await userEvent.click(blocked);

    expect(chosen).not.toHaveBeenCalled();
    expect(trigger().textContent).toBe("This machine");
  });

  it("is worked from the keyboard", async () => {
    const chosen = vi.fn();
    render(<Harness onChange={chosen} />);
    trigger().focus();
    await userEvent.keyboard("{Enter}");
    await screen.findByRole("listbox");
    // Past the option that cannot be chosen.
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    expect(chosen).toHaveBeenCalledWith("preview");
  });

  it("does not open when it is disabled", async () => {
    render(<Harness disabled />);
    await userEvent.click(trigger());

    expect(screen.queryByRole("listbox")).toBeNull();
  });
});
