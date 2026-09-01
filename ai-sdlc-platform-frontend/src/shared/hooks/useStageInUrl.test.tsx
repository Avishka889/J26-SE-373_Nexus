import { afterEach, describe, expect, it } from "vitest";
import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { useStageInUrl } from "./useStageInUrl";

afterEach(cleanup);

const STAGES = ["scope", "contract", "review"] as const;
type Stage = (typeof STAGES)[number];
function Phase() {
  const [stage, setStage] = useState<Stage>("scope");
  useStageInUrl(stage, setStage, STAGES);
  return (
    <p>
      <span data-testid="stage">{stage}</span>
      <button type="button" onClick={() => setStage("review")}>
        Open review
      </button>
    </p>
  );
}

function at(path: string) {
  window.history.replaceState(null, "", path);
  render(
    <BrowserRouter>
      <Phase />
    </BrowserRouter>,
  );
}

/**
 * The open stage was each phase's own state, so a reload, a way back or a
 * shared link always opened the first stage.
 */
describe("the open stage in the address", () => {
  it("opens the stage the address names", () => {
    at("/projects/p1/code?stage=contract");

    expect(screen.getByTestId("stage").textContent).toBe("contract");
    expect(window.location.search).toBe("?stage=contract");
  });

  it("writes the stage a reader opens, keeping the rest of the address", () => {
    at("/projects/p1/code?screen=s-1");

    fireEvent.click(screen.getByRole("button", { name: "Open review" }));

    expect(window.location.search).toBe("?screen=s-1&stage=review");
  });

  it("ignores a stage the phase does not have", () => {
    at("/projects/p1/code?stage=nowhere");

    expect(screen.getByTestId("stage").textContent).toBe("scope");
    expect(window.location.search).toBe("?stage=scope");
  });
});
