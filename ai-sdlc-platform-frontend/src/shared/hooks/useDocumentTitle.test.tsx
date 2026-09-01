import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { useDocumentTitle } from "./useDocumentTitle";

function Page({ title }: { title: string }) {
  useDocumentTitle(title);
  return null;
}

afterEach(cleanup);

/** Every page was titled "Nexus", whatever was open. */
describe("a page's title", () => {
  it("names the page, then the product, and is put back when the page goes", () => {
    document.title = "Nexus";
    const { rerender, unmount } = render(<Page title="Projects" />);
    expect(document.title).toBe("Projects | Nexus");

    rerender(<Page title="Testing & Security, Book Tracker" />);
    expect(document.title).toBe("Testing & Security, Book Tracker | Nexus");

    unmount();
    expect(document.title).toBe("Nexus");
  });
});
