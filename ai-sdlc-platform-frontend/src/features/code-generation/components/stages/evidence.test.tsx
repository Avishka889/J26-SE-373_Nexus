import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { codeApi } from "../../api";
import type { CodeSnapshot } from "../../api/types";
import { StageApiContract } from "./StageApiContract";
import { StageContractAgreement } from "./StageContractAgreement";
import { StageSprintScope } from "./StageSprintScope";

afterEach(cleanup);

/**
 * The evidence a stage cites did nothing, or opened the wrong place:
 * requirement chips had no target, "N screens" opened API Contract, a screen
 * chip opened Frontend Code, and finding locations were plain text.
 */
describe("evidence on the code page", () => {
  it("opens a story's requirement and its screens where they live", async () => {
    const snapshot = await codeApi.getCode("p1");
    const story = snapshot.scope!.stories.find(
      (one) => one.traces.requirementIds.length > 0 && one.traces.screenIds.length > 0,
    )!;
    const onOpenRequirement = vi.fn();
    const onOpenScreens = vi.fn();
    render(
      <StageSprintScope
        snapshot={snapshot}
        onToggle={vi.fn()}
        onPlanNextSprint={vi.fn()}
        onOpenScreens={onOpenScreens}
        onOpenRequirement={onOpenRequirement}
        busy={false}
      />,
    );

    fireEvent.click(screen.getAllByRole("button", { name: story.traces.requirementIds[0] })[0]);
    expect(onOpenRequirement).toHaveBeenCalledWith(story.traces.requirementIds[0]);
    fireEvent.click(screen.getAllByRole("button", { name: `${story.traces.screenIds.length} screens` })[0]);
    expect(onOpenScreens).toHaveBeenCalled();
  });

  it("opens an endpoint's requirement and screen, and a finding's file at its line", async () => {
    const snapshot = await codeApi.getCode("p1");
    const endpoint = snapshot.contract!.contract.endpoints.find(
      (one) => one.traces.requirementIds.length > 0 && one.traces.screenIds.length > 0,
    )!;
    const onJumpToScreen = vi.fn();
    const onOpenRequirement = vi.fn();
    render(
      <StageApiContract
        snapshot={snapshot}
        onChooseArm={vi.fn()}
        onJumpToScreen={onJumpToScreen}
        onOpenRequirement={onOpenRequirement}
        onDownloadOpenApi={vi.fn(async () => undefined)}
        busy={false}
      />,
    );

    fireEvent.click(screen.getAllByRole("button", { name: endpoint.traces.requirementIds[0] })[0]);
    expect(onOpenRequirement).toHaveBeenCalledWith(endpoint.traces.requirementIds[0]);
    fireEvent.click(screen.getAllByRole("button", { name: endpoint.traces.screenIds[0] })[0]);
    expect(onJumpToScreen).toHaveBeenCalledWith(endpoint.traces.screenIds[0]);
  });

  it("opens the file a finding cites, at its line", async () => {
    const snapshot = await codeApi.getCode("p1");
    const agreement = snapshot.agreement!;
    const cited = {
      ...snapshot,
      agreement: {
        ...agreement,
        findings: [
          {
            ...(agreement.findings[0] ?? {
              ruleId: "C1",
              severity: "error",
              subject: "GET /books",
              reason: "the contract declares it and nothing serves it",
              hint: null,
            }),
            severity: "error",
            location: { path: "apps/api/src/routes/books.ts", line: 42 },
          },
        ],
      },
    } as CodeSnapshot;
    const onOpenLocation = vi.fn();
    render(<StageContractAgreement snapshot={cited} onOpenLocation={onOpenLocation} />);

    fireEvent.click(screen.getByRole("button", { name: "apps/api/src/routes/books.ts:42" }));

    expect(onOpenLocation).toHaveBeenCalledWith("apps/api/src/routes/books.ts", 42);
  });
});

/** The OpenAPI document was out of reach, and conflicts were cut at eight with no word. */
describe("the contract's conflicts and its OpenAPI document", () => {
  it("shows every conflict on request, and downloads the document", async () => {
    const snapshot = await codeApi.getCode("p1");
    const contract = snapshot.contract!;
    const conflict = {
      endpointKey: "GET /books",
      field: "response",
      ruleValue: "Book[]",
      llmValue: "Book",
    };
    const many = {
      ...snapshot,
      contract: {
        ...contract,
        comparison: {
          ...contract.comparison!,
          conflicts: Array.from({ length: 11 }, (_, index) => ({ ...conflict, field: `field ${index}` })),
        },
      },
    } as CodeSnapshot;
    const onDownloadOpenApi = vi.fn(async () => undefined);
    render(
      <StageApiContract
        snapshot={many}
        onChooseArm={vi.fn()}
        onJumpToScreen={vi.fn()}
        onOpenRequirement={vi.fn()}
        onDownloadOpenApi={onDownloadOpenApi}
        busy={false}
      />,
    );

    expect(screen.getAllByText(/^GET \/books · field/)).toHaveLength(8);
    fireEvent.click(screen.getByRole("button", { name: "Show all 11 conflicts" }));
    expect(screen.getAllByText(/^GET \/books · field/)).toHaveLength(11);

    fireEvent.click(screen.getByRole("button", { name: /download openapi/i }));
    expect(onDownloadOpenApi).toHaveBeenCalled();
  });
});
