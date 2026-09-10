import { describe, expect, it } from "vitest";
import { deriveSeedFromInput } from "./deriveFromInput";

/**
 * The stand-in for Component 1 has to produce sentences, not fragments.
 *
 * A browser pass caught "As a user, I can work with a simple": the entity was
 * named from the first long word, which was an adjective. A story title that
 * stops mid-phrase reads as a broken app rather than a thin analysis.
 */
describe("deriveSeedFromInput", () => {
  const cases: [string, string][] = [
    ["Build a simple calculator app", "Calculator"],
    ["Create a basic recipe manager", "Recipe"],
    ["A small tool to track invoices", "Invoice"],
    ["Track workouts and workout history", "Workout"],
  ];

  for (const [input, expected] of cases) {
    it(`names the entity from "${input}"`, () => {
      const seed = deriveSeedFromInput("Demo", input);
      const entity = seed.nodes.find((n) => n.kind === "entity");
      expect(entity?.label).toBe(expected);
    });
  }

  it("writes a story title that is a whole sentence", () => {
    const seed = deriveSeedFromInput("Demo", "Build a simple calculator app");
    const story = seed.sprint.proposed[0];
    expect(story.title).toBe("As a user, I can work with a calculator");
    // The velocity line is composed as "Velocity is {basis}." so the basis must
    // not carry its own full stop.
    expect(seed.sprint.velocityAssumption.basis).not.toMatch(/\.$/);
    expect(`Velocity is ${seed.sprint.velocityAssumption.basis}.`).not.toContain("..");
  });

  it("keeps a thin input thin", () => {
    const seed = deriveSeedFromInput("Demo", "Build a simple calculator app");
    expect(seed.requirements.length).toBeLessThanOrEqual(4);
    for (const requirement of seed.requirements) {
      expect(requirement.lowConfidence).toBe(true);
    }
  });
});
