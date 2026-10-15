import { describe, expect, it } from "vitest";
import { HttpError } from "@/lib/http";
import type { CodeSnapshot } from "../api/types";
import { approvedVersion, refusedForSupersede } from "./supersede";

function snapshot(codeVersion: number, decision: { kind: string; version: number } | null) {
  return { codeVersion, gate: { decision, history: [] } } as unknown as CodeSnapshot;
}

/**
 * Approved code is replaced only after the reader says so.
 */
describe("the approved code version", () => {
  it("is the current one when the current one was approved", () => {
    expect(approvedVersion(snapshot(8, { kind: "approved", version: 8 }))).toBe(8);
  });

  // An accepted security fix wrote it over approved code: it has no review of
  // its own, and replacing it unasked left Testing nothing approved to run on.
  it("is the current one when a fix wrote it over an approved version", () => {
    const fixed = { ...snapshot(9, null), approvedThrough: 8 } as CodeSnapshot;

    expect(approvedVersion(fixed)).toBe(9);
  });

  it("is none when the current one was not, or was sent back", () => {
    expect(approvedVersion(snapshot(9, { kind: "approved", version: 8 }))).toBeNull();
    expect(approvedVersion(snapshot(8, { kind: "changes", version: 8 }))).toBeNull();
    expect(approvedVersion(snapshot(0, null))).toBeNull();
  });
});

describe("a refusal to replace approved code", () => {
  it("names the version a confirmation would replace", () => {
    const refusal = new HttpError("Code version 8 is approved", 409, {
      error: "code version 8 is approved",
      detail: { approvedVersion: 8, supersede: "required" },
    });

    expect(refusedForSupersede(refusal)).toBe(8);
  });

  it("is not any other refusal", () => {
    expect(refusedForSupersede(new HttpError("A run is in flight", 409, { error: "in flight" }))).toBeNull();
    expect(refusedForSupersede(new Error("nope"))).toBeNull();
  });
});
