import { describe, expect, it } from "vitest";
import type { Connection } from "@/entities/settings";
import { connectionStatus, verdictSentence, verdictTone } from "./connection";

function stored(verdict: "SUITABLE" | "WORKABLE" | "UNUSABLE" | null): Connection {
  return {
    provider: "github",
    connected: true,
    createdAt: "2026-10-04 09:00",
    createdBy: "u_1",
    tokenKind: "classic",
    scopes: [],
    probe: verdict ? { verdict, reason: "it answered", login: "ada" } : null,
  };
}

/**
 * "Connected" stayed green whatever the check said, because it meant only that
 * a credential was stored; the verdicts showed as raw SUITABLE, WORKABLE and
 * UNUSABLE, and a token that works with limits toasted as a success.
 */
describe("what a stored credential is known to do", () => {
  it("is what its last check said, in words", () => {
    expect(connectionStatus(stored("SUITABLE"))).toEqual({ label: "Connected", tone: "success" });
    expect(connectionStatus(stored("WORKABLE"))).toEqual({ label: "Works with limits", tone: "warning" });
    expect(connectionStatus(stored("UNUSABLE"))).toEqual({ label: "Not working", tone: "error" });
    expect(connectionStatus(stored(null))).toEqual({ label: "Saved, not checked", tone: "default" });
    expect(connectionStatus(undefined)).toEqual({ label: "Not connected", tone: "default" });
  });

  it("is said as a sentence, and toasted as what it is", () => {
    expect(verdictSentence({ verdict: "WORKABLE", reason: "no workflow scope", login: null })).toBe(
      "Works with limits: no workflow scope",
    );
    expect(verdictTone("WORKABLE")).toBe("warning");
    expect(verdictTone("UNUSABLE")).toBe("error");
    expect(verdictTone("SUITABLE")).toBe("success");
  });
});
