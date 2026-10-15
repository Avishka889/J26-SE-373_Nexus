import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createQueryClientOptions } from "@/lib/query";
import { codeApi } from "../api";
import { useCodeSnapshot } from "./useCode";

/**
 * Continue from an approved design opened a code page whose snapshot predated
 * the approval: it was younger than the cache's thirty seconds, so it was not
 * read again, and the page said the design "is being regenerated" until its
 * next read a minute later.
 */
describe("the code snapshot", () => {
  it("is read afresh each time the page opens", async () => {
    const asked = vi.spyOn(codeApi, "getCode");
    const client = new QueryClient(createQueryClientOptions());
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const first = renderHook(() => useCodeSnapshot("p1"), { wrapper });
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    first.unmount();
    const second = renderHook(() => useCodeSnapshot("p1"), { wrapper });
    await waitFor(() => expect(asked).toHaveBeenCalledTimes(2));

    second.unmount();
    asked.mockRestore();
  });
});
