import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { codeKeys } from "@/lib/query";
import { nexuspaySeed } from "@/entities/design-seed/projects/nexuspay";
import { buildSnapshot, resetDesignDb, writeDesign } from "../fixtures/designDb";
import { useDesignMutations } from "./useDesign";

const PROJECT = "p1";

beforeEach(() => {
  resetDesignDb();
  writeDesign(PROJECT, buildSnapshot(PROJECT, nexuspaySeed, "awaiting"));
});

/**
 * Right after an approval the code page said the design "is being
 * regenerated": it had read the code snapshot before the decision and asked
 * again only once a minute while nothing generated.
 */
describe("a design decision", () => {
  it("has the code page read again", async () => {
    const client = new QueryClient();
    client.setQueryData(codeKeys.snapshot(PROJECT), { codeVersion: 0 });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useDesignMutations(PROJECT), { wrapper });

    await act(() =>
      result.current.submitGateDecision.mutateAsync({ kind: "approved", by: "A. Chen" }),
    );

    expect(client.getQueryState(codeKeys.snapshot(PROJECT))?.isInvalidated).toBe(true);
  });
});
