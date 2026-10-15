import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useSupersede } from "./useSupersede";

/**
 * Generate again, a scope change and a new arm ask first over approved code.
 */
describe("starting a new code version", () => {
  it("goes ahead at once when nothing approved would be replaced", () => {
    const { result } = renderHook(() => useSupersede());
    const action = vi.fn();

    act(() => result.current.guard(null, action));

    expect(action).toHaveBeenCalledWith(false);
    expect(result.current.ask).toBeNull();
  });

  it("asks first over an approved version, and supersedes it only on yes", () => {
    const { result } = renderHook(() => useSupersede());
    const action = vi.fn();

    act(() => result.current.guard(8, action));
    expect(action).not.toHaveBeenCalled();
    expect(result.current.ask?.version).toBe(8);

    act(() => result.current.confirm());
    expect(action).toHaveBeenCalledWith(true);
    expect(result.current.ask).toBeNull();
  });

  it("does nothing when the reader keeps the approved version", () => {
    const { result } = renderHook(() => useSupersede());
    const action = vi.fn();

    act(() => result.current.guard(8, action));
    act(() => result.current.cancel());

    expect(action).not.toHaveBeenCalled();
    expect(result.current.ask).toBeNull();
  });
});
