import { describe, expect, it } from "vitest";
import { compareServerTimes, formatWhen, parseServerTime } from "./time";

/**
 * The tests run in Colombo's zone (vitest.config.ts), five and a half hours
 * ahead of UTC: the half hour catches a conversion that only moves hours.
 */
describe("a server time", () => {
  it("is shown in the reader's zone when it carries its own", () => {
    expect(formatWhen("2026-10-03T09:12:00Z")).toBe("2026-10-03 14:42");
    expect(formatWhen("2026-10-03T09:12:41.123456+00:00")).toBe("2026-10-03 14:42");
  });

  it("is read as UTC in the older shape, which always was", () => {
    expect(formatWhen("2026-10-03 09:12")).toBe("2026-10-03 14:42");
  });

  it("moves to the next day when the zone does", () => {
    expect(formatWhen("2026-10-03T20:00:00Z")).toBe("2026-10-04 01:30");
  });

  it("is never guessed from a time without a zone", () => {
    expect(parseServerTime("2026-10-03T09:12:00")).toBeNull();
    expect(parseServerTime("2026-10-03")).toBeNull();
  });

  it("shows text that is not a time as it is", () => {
    expect(formatWhen("still running")).toBe("still running");
    expect(formatWhen("09:12")).toBe("09:12");
    expect(formatWhen(null)).toBe("");
  });

  it("orders by the moment, whatever the shape", () => {
    // As text the newer value sorts first: a space sorts before a T.
    expect(compareServerTimes("2026-10-03 09:30", "2026-10-03T09:12:00Z")).toBeGreaterThan(0);
    expect(compareServerTimes("2026-10-03T09:12:00Z", "2026-10-03 09:12")).toBe(0);
    expect(compareServerTimes(undefined, "2026-10-03 09:12")).toBeLessThan(0);
  });
});
