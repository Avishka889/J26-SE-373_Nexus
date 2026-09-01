import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Field } from "./Field";

/**
 * A field's hint sits behind an info icon beside its label, as
 * `docs/tooltip_image.png` draws it, and is the field's description rather than
 * part of its name. The label still names the control, which is what a click on
 * it, a screen reader and "find the field called Cluster" all rely on.
 */
afterEach(cleanup);

const HINT = "The cluster's name in that project; the free M0 tier is enough";

function shown(tip: HTMLElement): boolean {
  return tip.className.split(/\s+/).includes("visible");
}

describe("a field with a hint", () => {
  it("is named by its label alone, and described by its hint", () => {
    render(
      <Field label="Cluster" hint={HINT}>
        <input />
      </Field>,
    );

    const input = screen.getByRole("textbox", { name: "Cluster" });
    expect(screen.getByLabelText("Cluster")).toBe(input);
    const described = input.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(described)?.textContent).toBe(HINT);
  });

  it("shows the hint while the icon is hovered or focused, and Escape closes it", () => {
    render(
      <Field label="Cluster" hint={HINT}>
        <input />
      </Field>,
    );
    const icon = screen.getByRole("button", { name: "About Cluster" });
    const tip = screen.getByRole("tooltip", { hidden: true });
    expect(tip.textContent).toBe(HINT);
    expect(shown(tip)).toBe(false);

    fireEvent.mouseEnter(icon.parentElement as HTMLElement);
    expect(shown(tip)).toBe(true);
    fireEvent.mouseLeave(icon.parentElement as HTMLElement);
    expect(shown(tip)).toBe(false);

    fireEvent.focus(icon);
    expect(shown(tip)).toBe(true);
    fireEvent.keyDown(icon, { key: "Escape" });
    expect(shown(tip)).toBe(false);
  });

  it("keeps the hint out of the label, where a button would take the label for itself", () => {
    const { container } = render(
      <Field label="Cluster" hint={HINT}>
        <input />
      </Field>,
    );
    const label = container.querySelector("label");
    expect(label?.textContent).toBe("Cluster");
    expect(label?.querySelector("button")).toBeNull();
  });
});

describe("a field whose control is wrapped", () => {
  it("hands the ids to the control through a function", () => {
    render(
      <Field label="Email" hint="Where the receipts go">
        {(control) => (
          <div className="relative">
            <span aria-hidden="true">@</span>
            <input {...control} type="email" />
          </div>
        )}
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "Email" });
    expect(
      document.getElementById(input.getAttribute("aria-describedby") ?? "")
        ?.textContent,
    ).toBe("Where the receipts go");
  });

  it("keeps an id the control already has", () => {
    render(
      <Field label="Note">
        <textarea id="phase-note" />
      </Field>,
    );
    expect(screen.getByLabelText("Note").id).toBe("phase-note");
  });
});

describe("a field that shows something rather than asks for it", () => {
  it("is a group captioned by its label and described by its hint", () => {
    render(
      <Field label="What the token can do" hint="Read by the probe">
        <div>repo, workflow</div>
      </Field>,
    );
    const group = screen.getByRole("group", { name: "What the token can do" });
    expect(
      document.getElementById(group.getAttribute("aria-describedby") ?? "")
        ?.textContent,
    ).toBe("Read by the probe");
  });
});
