import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { ActivityLogEntry } from "../api/types";
import { TimelineEntry } from "./TimelineEntry";

afterEach(cleanup);

function entry(title: string, category: ActivityLogEntry["category"], outcome: ActivityLogEntry["outcome"]) {
  const one: ActivityLogEntry = {
    id: title,
    timestamp: "2026-10-04T09:00:00+00:00",
    title,
    description: "",
    actor: "Ada",
    category,
    outcome,
  };
  render(<TimelineEntry entry={one} isDark={false} isLast />);
}

/**
 * The mark came from the category: a change request at a review drew the
 * green success check, and a failed run the Design pencil.
 */
describe("an activity entry's mark", () => {
  it("says a failed run failed", () => {
    entry("Run failed", "deployment", "failed");

    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.queryByText("Succeeded")).toBeNull();
  });

  it("says a change request asked for changes, not that something succeeded", () => {
    entry("Requested code changes", "approval", "changes");

    expect(screen.getByText("Changes requested")).toBeTruthy();
    expect(screen.queryByText("Succeeded")).toBeNull();
  });

  it("says an approval succeeded", () => {
    entry("Approved the design", "approval", "done");

    expect(screen.getByText("Succeeded")).toBeTruthy();
  });
});

/**
 * The server sent a date it formatted in UTC, so an event late in a Colombo
 * evening showed the day before, and no event showed its time at all.
 */
describe("an activity entry's time", () => {
  it("is the reader's local date and time of day", () => {
    entry("Approved the design", "approval", "done");

    const time = screen.getByText("2026-10-04 14:30");
    expect(time.tagName).toBe("TIME");
    expect(time.getAttribute("datetime")).toBe("2026-10-04T09:00:00+00:00");
  });
});
