import { afterEach, describe, expect, it, vi } from "vitest";
import { scrollMotion } from "./motion";

afterEach(() => {
  vi.unstubAllGlobals();
});

function prefers(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({ matches: reduced && query.includes("reduce"), media: query })),
  );
}

/** Every scripted scroll glided, whatever the reader had asked their system for. */
describe("a scroll the page makes", () => {
  it("jumps when the reader asked for less motion", () => {
    prefers(true);
    expect(scrollMotion()).toBe("auto");
  });

  it("glides otherwise", () => {
    prefers(false);
    expect(scrollMotion()).toBe("smooth");
  });
});
