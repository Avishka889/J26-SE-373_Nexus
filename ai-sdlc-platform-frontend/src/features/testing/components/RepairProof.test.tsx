import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { failures } from "../fixtures/failures";
import { RepairProof } from "./RepairProof";

afterEach(cleanup);

describe("a repair known only as its patch", () => {
  // Laid out as before and after, it showed an empty "before" and the raw
  // diff as the "after".
  it("shows the patch as a diff of the file it changes", () => {
    const repair = {
      ...failures.find((one) => one.repair)!.repair!,
      original: "",
      path: "apps/api/test/books.test.ts",
      proposed: "@@ -4,1 +4,1 @@\n-  expect(status).toBe(200);\n+  expect(status).toBe(201);",
    };

    render(<RepairProof repair={repair} />);

    expect(screen.getByText("apps/api/test/books.test.ts")).toBeTruthy();
    expect(screen.getByText(/^\+ expect\(status\)\.toBe\(201\);$/)).toBeTruthy();
    expect(screen.queryByText("Test today")).toBeNull();
  });
});
