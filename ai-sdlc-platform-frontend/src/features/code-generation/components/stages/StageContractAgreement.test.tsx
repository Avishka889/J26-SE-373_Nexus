import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CODE_STAGE_IDS } from "@/types/project";
import type { CodeSnapshot, CodeStages } from "../../api/types";
import { StageContractAgreement } from "./StageContractAgreement";

afterEach(cleanup);

function snapshot(): CodeSnapshot {
  const stages = Object.fromEntries(
    CODE_STAGE_IDS.map((id) => [
      id,
      { id, status: "pending" as const, generatedFromVersion: 0, generatedAt: null, summary: null, error: null },
    ]),
  ) as CodeStages;
  return {
    projectId: "p1",
    codeVersion: 1,
    designVersion: 1,
    designBlocker: null,
    generatedFromDesignVersion: 1,
    stages,
    run: null,
    gate: { decision: null, history: [] },
    approvedThrough: null,
    scope: null,
    nextSprint: null,
    techStack: null,
    contract: null,
    agreement: {
      contractVersion: 1,
      findings: [
        {
          ruleId: "form-not-wired",
          severity: "warning",
          reason: "apps/web/src/pages/ShopCheckoutPage.tsx shows a form whose fields nothing saves",
          hint: "Say in the design what this form saves.",
          subject: "apps/web/src/pages/ShopCheckoutPage.tsx",
          location: { path: "apps/web/src/pages/ShopCheckoutPage.tsx", line: 12 },
        },
      ],
      counts: {
        endpointsTotal: 4,
        endpointsImplemented: 3,
        endpointsMissing: ["post-orders"],
        endpointsCalled: 3,
        endpointsUnused: [],
        orphanRoutes: [],
        foreignCalls: [],
        schemaMismatches: 0,
        agreementRate: 0.75,
      },
    },
    repository: null,
    diff: null,
    thread: [],
  };
}

describe("the agreement counts", () => {
  // "Implemented" counted registered routes, so a route that answers without
  // doing anything counted as implemented (review item C2-3).
  it("say routes registered, and name the ones that are not", () => {
    render(<StageContractAgreement snapshot={snapshot()} onOpenLocation={vi.fn()} />);

    expect(screen.getByText("Routes registered")).toBeTruthy();
    expect(screen.getByText("Not registered")).toBeTruthy();
    expect(screen.queryByText("Implemented")).toBeNull();
    const forms = screen.getByText("Forms nothing saves").parentElement;
    expect(forms?.querySelector(".tp-num")?.textContent).toBe("1");
  });
});
