import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Finding } from "../../../fixtures/types";
import { SecurityFindingDetail } from "./SecurityFindingDetail";

afterEach(cleanup);

const LIVE: Finding = {
  id: "CWE-89:orders:36",
  cwe: "CWE-89",
  name: "SQL injection",
  severity: "high",
  cvss: 8.1,
  file: "apps/api/src/routes/orders.ts",
  line: 36,
  status: "open",
  foundBy: ["local"],
  explanation: "The order id reaches the query unparameterised.",
  proposal: {
    id: "rp-1",
    summary: "Use a parameterised query.",
    hunks: [{ path: "apps/api/src/routes/orders.ts", diff: "-db.query(`... ${id}`)\n+db.query('... $1', [id])" }],
    state: "proposed",
    risk: "Low risk: the patch changes 2 lines in 1 file.",
    appliedCodeVersion: null,
  },
};

function detail(finding: Finding) {
  const onApplyFix = vi.fn();
  const onDismiss = vi.fn();
  const onAccept = vi.fn();
  render(
    <SecurityFindingDetail
      finding={finding}
      onApplyFix={onApplyFix}
      onDismiss={onDismiss}
      onAccept={onAccept}
      onGoTo={vi.fn()}
    />,
  );
  return { onApplyFix, onDismiss, onAccept };
}

/**
 * A live finding can be fixed or dismissed, and a dismissal says why.
 */
describe("a live security finding", () => {
  it("shows its proposed fix and offers to apply it", () => {
    const { onApplyFix } = detail(LIVE);

    expect(screen.getByText("Use a parameterised query.")).toBeTruthy();
    expect(screen.getByText("+db.query('... $1', [id])")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Apply fix" }));

    expect(onApplyFix).toHaveBeenCalledWith("CWE-89:orders:36");
  });

  it("is dismissed only with a reason, which is sent", () => {
    const { onDismiss } = detail({ ...LIVE, proposal: undefined });

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    const send = screen.getByRole("button", { name: "Dismiss with this reason" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Why this finding is dismissed"), {
      target: { value: "The id is a UUID validated upstream." },
    });
    fireEvent.click(send);

    expect(onDismiss).toHaveBeenCalledWith("CWE-89:orders:36", "The id is a UUID validated upstream.");
  });
});

/**
 * Over newer code than may ship, a fix reaches production only with that code,
 * and the place to say so is beside the button that writes it (C4-13).
 */
describe("a fix over newer code than may ship", () => {
  const SHIPS =
    "A fix applied now goes into code version 3, sprint 2's build, and reaches production with sprint 2, once its tests are approved.";
  const show = (finding: Finding) =>
    render(
      <SecurityFindingDetail
        finding={finding}
        shipsWith={SHIPS}
        onApplyFix={vi.fn()}
        onDismiss={vi.fn()}
        onAccept={vi.fn()}
        onGoTo={vi.fn()}
      />,
    );

  it("says what it ships with, beside Apply fix", () => {
    show(LIVE);

    expect(screen.getByText(SHIPS)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Apply fix" })).toBeTruthy();
  });

  it("says nothing of it once the fix is applied", () => {
    show({ ...LIVE, status: "fix-applied" });

    expect(screen.queryByText(SHIPS)).toBeNull();
  });
});

/**
 * A real Critical or High weakness can ship only with its risk accepted in
 * words, which the release gate reads (G8, review item C3-8). The page offered
 * no way to say it, only Apply fix and Dismiss.
 */
describe("accepting a finding's risk", () => {
  it("is done only with a reason, which is sent", () => {
    const { onAccept } = detail(LIVE);

    fireEvent.click(screen.getByRole("button", { name: "Accept the risk" }));
    const send = screen.getByRole("button", {
      name: "Accept the risk with this reason",
    }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Why this can ship as it is"), {
      target: { value: "Behind the admin login until sprint 2." },
    });
    fireEvent.click(send);

    expect(onAccept).toHaveBeenCalledWith("CWE-89:orders:36", "Behind the admin login until sprint 2.");
  });

  it("says so once accepted, and does not ask again", () => {
    detail({ ...LIVE, riskAccepted: "Behind the admin login until sprint 2." });

    expect(screen.getByText("Risk accepted: Behind the admin login until sprint 2.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Accept the risk" })).toBeNull();
  });
});

describe("while another fix waits for its run", () => {
  it("offers Apply fix no more, and says why", () => {
    const why = "The CWE-89 fix in apps/api/src/Accounts.java is applied as code version 2, which no testing run has measured yet.";
    render(
      <SecurityFindingDetail
        finding={LIVE}
        applyBlocked={why}
        onApplyFix={vi.fn()}
        onDismiss={vi.fn()}
        onAccept={vi.fn()}
        onGoTo={vi.fn()}
      />,
    );

    const apply = screen.getByRole("button", { name: "Apply fix" }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    expect(screen.getByText(why)).toBeTruthy();
  });
});
