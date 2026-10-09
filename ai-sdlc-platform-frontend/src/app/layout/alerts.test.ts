import { describe, expect, it } from "vitest";
import { alertsFor, alertsFromAttention } from "./alerts";

/** The bell invents nothing in the running app; the demo keeps its two lines. */
describe("the bell", () => {
  it("shows nothing in the running app", () => {
    expect(alertsFor(false, "Book Tracker", "gpt-4o")).toEqual([]);
  });

  it("keeps the demo's two lines on fixtures", () => {
    expect(
      alertsFor(true, "NotifyHub", "gpt-4o").map((one) => one.title),
    ).toEqual(["Approval needed", "AI model ready"]);
  });
});

/**
 * The bell said "Nothing needs you right now" while thirty seven reviews
 * waited. In the running app it lists what the server says waits on the
 * signed-in person, each line opening the page where it is decided.
 */
describe("the bell in the running app", () => {
  it("lists what waits, each opening its phase", () => {
    const alerts = alertsFromAttention([
      {
        id: "rollback:d1",
        kind: "rollback",
        projectId: "p_1",
        projectName: "Task Tracker",
        phase: "deployment",
        title: "A rollback waits for your decision",
        message: "Deploy version 2 stopped serving what was released.",
        at: "2026-10-03T09:00:00Z",
      },
      {
        id: "review:g1",
        kind: "review",
        projectId: "p_2",
        projectName: "Cold Chain",
        phase: "design",
        title: "Design Review waiting",
        message: "Version 3 waits on your review.",
        at: "2026-10-01T09:00:00Z",
      },
    ]);

    expect(alerts.map((one) => [one.title, one.href])).toEqual([
      ["A rollback waits for your decision", "/projects/p_1/deployment"],
      ["Design Review waiting", "/projects/p_2/requirements"],
    ]);
    expect(alerts[1].message).toBe("Cold Chain: Version 3 waits on your review.");
    expect(alerts[0].severity).toBe("warning");
  });
});
