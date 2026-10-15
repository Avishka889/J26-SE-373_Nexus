import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { codeApi } from "../../api";
import { StageTechStack } from "./StageTechStack";

afterEach(cleanup);

/**
 * "Recommended" sat on a stack the platform cannot generate yet, beside a
 * Select only another stack had: Cold Chain's scoring put React and Spring
 * Boot first.
 */
describe("the recommended stack", () => {
  it("is the best one that can be generated, and the top score says so apart", async () => {
    const snapshot = await codeApi.getCode("p1");
    const stack = snapshot.techStack!;
    // The scoring's top stack is one the generators cannot build yet.
    const springFirst = {
      ...snapshot,
      techStack: { ...stack, recommendedId: "react-spring-postgres" },
    };

    render(<StageTechStack snapshot={springFirst} onSelect={vi.fn()} busy={false} />);

    const card = (name: string) =>
      screen.getByText(name, { selector: "p" }).closest("div.rounded-xl") as HTMLElement;
    expect(within(card("MERN")).getByText("recommended")).toBeTruthy();
    expect(within(card("React and Spring Boot")).queryByText("recommended")).toBeNull();
    expect(within(card("React and Spring Boot")).getByText("highest score")).toBeTruthy();
  });
});
