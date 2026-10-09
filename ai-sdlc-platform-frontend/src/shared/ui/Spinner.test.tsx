import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { PageLoader, Spinner } from "./Spinner";

afterEach(cleanup);

describe("the loading indicator", () => {
  it("announces its label, unless words beside it already say it", () => {
    render(<Spinner label="Reading the file" />);
    expect(screen.getByRole("status", { name: "Reading the file" })).toBeTruthy();
    cleanup();
    const { container } = render(<Spinner decorative />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(container.querySelector("[data-spinner]")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("is what a page shows while it loads, with no words on screen", () => {
    const { container } = render(<PageLoader label="Loading the design" />);
    expect(screen.getByRole("status", { name: "Loading the design" })).toBeTruthy();
    expect(container.textContent).toBe("");
  });
});

/**
 * Every loading state uses this spinner. The app had three: lucide's Loader2
 * turned by `animate-spin` or `tp-spin`, plain bordered rings, and words such
 * as "Loading the design" on their own. A generic spinner creeping back fails
 * here, naming the file.
 */
describe("one spinner across the app", () => {
  const root = join(__dirname, "..", "..");
  const allowed = new Set([join("shared", "ui", "Spinner.tsx"), join("shared", "ui", "Spinner.test.tsx")]);

  function sources(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return sources(path);
      return /\.(ts|tsx)$/.test(name) ? [path] : [];
    });
  }

  it("has no other spinner anywhere", () => {
    const offenders = sources(root)
      .filter((path) => !allowed.has(relative(root, path)))
      .filter((path) => /\bLoader2\b|animate-spin|\btp-spin\b/.test(readFileSync(path, "utf8")))
      .map((path) => relative(root, path));
    expect(offenders).toEqual([]);
  });
});
