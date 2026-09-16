import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { codeApi } from "../api";
import { FileViewer } from "./FileViewer";

afterEach(cleanup);

/** A finding's location was plain text; it opens the file at the line it cites. */
describe("a file opened at a cited line", () => {
  it("marks that line", async () => {
    const snapshot = await codeApi.getCode("p1");
    const path = snapshot.repository!.manifest[0].path;
    const content = (await codeApi.getFile("p1", path, snapshot.codeVersion)).content;
    const second = content.split("\n")[1];

    render(
      <QueryClientProvider client={new QueryClient()}>
        <FileViewer
          projectId="p1"
          path={path}
          version={snapshot.codeVersion}
          line={2}
          onClose={vi.fn()}
        />
      </QueryClientProvider>,
    );

    const cited = await screen.findByText(second, { selector: "[data-cited-line]" });
    expect(cited).toBeTruthy();
  });
});
