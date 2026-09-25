import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { buildTestSnapshot } from "../../fixtures/buildTestSnapshot";
import type { Finding } from "../../fixtures/types";
import { SEVERITY_ORDER } from "../../model/process";
import { buildView } from "../../model/view";
import { StepSecurity } from "./StepSecurity";

afterEach(cleanup);

const FINDING: Finding = {
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
    hunks: [{ path: "apps/api/src/routes/orders.ts", diff: "-a\n+b" }],
    state: "proposed",
    risk: "Low risk: the patch changes 2 lines in 1 file.",
    appliedCodeVersion: null,
  },
};

describe("the security step", () => {
  // Where a fix ships has to reach the button it is about (review item C4-13).
  it("hands where a fix ships down to the finding's Apply fix", () => {
    const ships = "A fix applied now goes into code version 3, sprint 2's build.";
    const view = {
      ...buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" }),
      findings: [FINDING],
      fixShipsWith: ships,
    };

    render(
      <StepSecurity
        view={view}
        severityOrder={SEVERITY_ORDER}
        detectorComparison={null}
        expandedId={FINDING.id}
        onExpand={vi.fn()}
        onApplyFix={vi.fn()}
        onDismiss={vi.fn()}
        onAccept={vi.fn()}
        onGoTo={vi.fn()}
      />,
    );

    expect(screen.getByText(ships)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Apply fix" })).toBeTruthy();
  });

  // Which tools scanned, and why one did not (review item C3-5).
  it("lists each scanning tool's outcome", () => {
    const failed = "npm audit did not run: npm reported ENOTFOUND: request failed";
    const view = {
      ...buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" }),
      scanTools: ["semgrep 1.90.0 ran", failed],
    };

    render(
      <StepSecurity
        view={view}
        severityOrder={SEVERITY_ORDER}
        detectorComparison={null}
        expandedId={null}
        onExpand={vi.fn()}
        onApplyFix={vi.fn()}
        onDismiss={vi.fn()}
        onAccept={vi.fn()}
        onGoTo={vi.fn()}
      />,
    );

    expect(screen.getByText("semgrep 1.90.0 ran")).toBeTruthy();
    expect(screen.getByText(failed)).toBeTruthy();
  });

  // And why no fix can be applied yet, while another waits for its run (C3-9).
  it("hands a fix waiting for its run down to every other Apply fix", () => {
    const waiting =
      "The CWE-79 fix in apps/web/src/pages/Orders.tsx is applied as code version 3, which no testing run has measured yet: run the tests on code version 3 first, then apply another fix.";
    const view = {
      ...buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" }),
      findings: [FINDING],
      fixAwaitingItsRun: waiting,
    };

    render(
      <StepSecurity
        view={view}
        severityOrder={SEVERITY_ORDER}
        detectorComparison={null}
        expandedId={FINDING.id}
        onExpand={vi.fn()}
        onApplyFix={vi.fn()}
        onDismiss={vi.fn()}
        onAccept={vi.fn()}
        onGoTo={vi.fn()}
      />,
    );

    expect(screen.getByText(waiting)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Apply fix" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

/**
 * A scan that refuses a candidate says so. Twelve npm audit advisories were
 * refused for having no line in the repository, and the page read "0
 * findings" with no word of them: a reader took it that there were none.
 */
describe("the candidates a scan refused", () => {
  const refused = (n: number) =>
    Array.from({ length: n }, (_, i) => ({
      origin: "scanner",
      cwe: `CWE-${20 + i}`,
      reason: "no-evidence",
      path: "package.json",
      line: 0,
      detail: `npm audit: advisory ${i + 1}`,
    }));

  function scan(count: number) {
    const view = {
      ...buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" }),
      findings: [],
      refused: refused(count),
    };
    render(
      <StepSecurity
        view={view}
        severityOrder={SEVERITY_ORDER}
        detectorComparison={null}
        expandedId={null}
        onExpand={vi.fn()}
        onApplyFix={vi.fn()}
        onDismiss={vi.fn()}
        onAccept={vi.fn()}
        onGoTo={vi.fn()}
      />,
    );
  }

  it("are counted beside the findings, and listed with why each was refused", () => {
    scan(2);

    expect(screen.getByText(/2 candidates refused, listed below/)).toBeTruthy();
    expect(screen.getByText("2 candidates were refused")).toBeTruthy();
    expect(screen.getByText("npm audit: advisory 1")).toBeTruthy();
    expect(screen.getAllByText(/CWE-20 · no line of the repository was given/)).toHaveLength(1);
  });

  it("say why an advisory against a package is always refused", () => {
    scan(2);

    expect(screen.getByText(/npm audit reports an advisory against a package, not a line/)).toBeTruthy();
  });

  it("show five and offer the rest", () => {
    scan(12);

    expect(screen.getByText("npm audit: advisory 5")).toBeTruthy();
    expect(screen.queryByText("npm audit: advisory 6")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show all 12" }));
    expect(screen.getByText("npm audit: advisory 12")).toBeTruthy();
  });

  it("say nothing when nothing was refused", () => {
    scan(0);

    expect(screen.queryByText(/candidates? (were|was) refused/)).toBeNull();
    expect(screen.queryByText(/listed below/)).toBeNull();
  });
});

/**
 * A scan with no findings drew the table's headings over nothing, and a title
 * saying two detectors had run whatever had.
 */
describe("a scan that raised nothing", () => {
  function scan(scanTools: string[]) {
    const view = {
      ...buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" }),
      findings: [],
      refused: [],
      scanTools,
    };
    render(
      <StepSecurity
        view={view}
        severityOrder={SEVERITY_ORDER}
        detectorComparison={null}
        expandedId={null}
        onExpand={vi.fn()}
        onApplyFix={vi.fn()}
        onDismiss={vi.fn()}
        onAccept={vi.fn()}
        onGoTo={vi.fn()}
      />,
    );
  }

  it("says there are no findings, in place of an empty table", () => {
    scan(["semgrep 1.180.0 ran", "npm audit ran"]);

    expect(screen.getByText("No findings at test version 1.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("names the tools that ran, not a number of detectors", () => {
    scan(["semgrep 1.180.0 ran", "npm audit ran"]);

    expect(screen.getByText("What semgrep 1.180.0 and npm audit raised")).toBeTruthy();
    expect(screen.queryByText(/Two detectors ran/)).toBeNull();
  });

  it("says so when a tool did not run", () => {
    scan(["semgrep 1.180.0 ran", "npm audit did not run: no lockfile"]);

    expect(screen.getByText("What semgrep 1.180.0 raised")).toBeTruthy();
  });
});
