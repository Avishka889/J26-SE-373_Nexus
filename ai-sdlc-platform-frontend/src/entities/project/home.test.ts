import { describe, expect, it } from "vitest";
import type { ProjectStatus } from "@/types/project";
import { projectHomePath } from "./home";

/**
 * Every way into a project landed on Requirements and Design, so a project
 * waiting at its test review opened three phases from its decision.
 */
describe("where opening a project takes you", () => {
  it.each<[ProjectStatus, string]>([
    ["draft", "requirements"],
    ["design", "requirements"],
    ["code", "code"],
    ["testing", "testing"],
    ["deploy", "deployment"],
    ["complete", "deployment"],
  ])("a project in %s opens at %s", (status, phase) => {
    expect(projectHomePath({ id: "p1", status })).toBe(`/projects/p1/${phase}`);
  });
});
