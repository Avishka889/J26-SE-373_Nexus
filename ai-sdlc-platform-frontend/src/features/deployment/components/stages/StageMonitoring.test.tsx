import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { buildDeploySnapshot } from "../../fixtures/buildDeploySnapshot";
import { buildView } from "../../model/view";
import { StageMonitoring } from "./StageMonitoring";

afterEach(cleanup);

describe("the probes a window measured", () => {
  it("reads latencies in whole milliseconds, as the orchestrator measures them to the microsecond", () => {
    // The demo's latencies are whole numbers; the live walkthrough's were not,
    // and the table printed "30.36523499758914 ms".
    const snapshot = buildDeploySnapshot("p4", "deploy");
    if (!snapshot.monitoring) throw new Error("the demo has a monitoring report");
    const [first, ...rest] = snapshot.monitoring.probes;
    const measured = {
      ...snapshot,
      monitoring: {
        ...snapshot.monitoring,
        probes: [{ ...first, p50Ms: 30.36523499758914, p95Ms: 52.59556698729284 }, ...rest],
      },
    };
    render(
      <StageMonitoring
        view={buildView(measured)}
        busy={false}
        watching={false}
        onWatch={vi.fn()}
        onDecideFeedback={vi.fn()}
        onSendFeedback={vi.fn()}
        isDark={false}
      />,
    );

    expect(screen.getByText("30 ms")).toBeTruthy();
    expect(screen.getByText("53 ms")).toBeTruthy();
    expect(screen.queryByText(/30\.365/)).toBeNull();
  });
});

describe("the release a window watched", () => {
  it("names its state in a sentence that reads", () => {
    // The live walkthrough's page said "which is succeeded": the ledger's word
    // dropped into "which is ...", which also made "which is failed".
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const watchedId = snapshot.monitoring?.deploymentId;
    const settled = {
      ...snapshot,
      deployments: snapshot.deployments.map((one) =>
        one.id === watchedId ? { ...one, state: "succeeded" as const } : one,
      ),
    };
    render(
      <StageMonitoring
        view={buildView(settled)}
        busy={false}
        watching={false}
        onWatch={vi.fn()}
        onDecideFeedback={vi.fn()}
        onSendFeedback={vi.fn()}
        isDark={false}
      />,
    );

    expect(screen.getByText(/The last window watched deploy version \d+, which succeeded\./)).toBeTruthy();
    expect(screen.queryByText(/which is succeeded/)).toBeNull();
  });
});

/**
 * "Send to requirements" opened a design version and ran a paid regeneration
 * of every design stage in one click, with nothing saying so; and Dismiss was
 * enabled without its required note, only to be refused.
 */
describe("feedback for requirements", () => {
  function show(count: number) {
    const snapshot = buildDeploySnapshot("p4", "deploy");
    if (!snapshot.feedback) throw new Error("the demo has feedback");
    const [first] = snapshot.feedback.items;
    const items = Array.from({ length: count }, (_, index) => ({
      ...first,
      id: `fb-${index}`,
      summary: `Suggestion ${index + 1}`,
    }));
    const onSendFeedback = vi.fn(async () => true);
    render(
      <StageMonitoring
        view={buildView({ ...snapshot, feedback: { ...snapshot.feedback, items } })}
        busy={false}
        watching={false}
        onWatch={vi.fn()}
        onDecideFeedback={vi.fn()}
        onSendFeedback={onSendFeedback}
        isDark={false}
      />,
    );
    return { onSendFeedback };
  }

  it("asks before sending, saying the design runs again", () => {
    const { onSendFeedback } = show(1);

    fireEvent.click(screen.getByRole("button", { name: /send to requirements/i }));

    expect(onSendFeedback).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toMatch(/runs Requirements and Design again on every stage/);
    fireEvent.click(screen.getAllByRole("button", { name: "Send to requirements" }).at(-1)!);
    expect(onSendFeedback).toHaveBeenCalledWith(["fb-0"]);
  });

  it("sends several as one change", () => {
    const { onSendFeedback } = show(3);

    fireEvent.click(screen.getByRole("button", { name: /send all 3 as one change/i }));
    fireEvent.click(screen.getAllByRole("button", { name: "Send to requirements" }).at(-1)!);

    expect(onSendFeedback).toHaveBeenCalledWith(["fb-0", "fb-1", "fb-2"]);
  });

  it("holds Dismiss until the reason is written", () => {
    show(1);

    const dismiss = screen.getByRole("button", { name: "Dismiss" }) as HTMLButtonElement;
    expect(dismiss.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/note, required to dismiss/i), {
      target: { value: "a planned outage" },
    });
    expect(dismiss.disabled).toBe(false);
  });
});
