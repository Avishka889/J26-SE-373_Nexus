import { describe, expect, it } from "vitest";
import type { Project } from "@/types/project";
import { triage } from "./triage";

const project = (over: Partial<Project>): Project =>
  ({
    id: "p",
    name: "P",
    description: "",
    requirementText: "",
    status: "design",
    createdAt: "2026-10-01T00:00:00Z",
    updatedAt: "2026-10-01T00:00:00Z",
    ...over,
  }) as Project;

const all = [
  project({ id: "a", name: "ledger", status: "testing", createdAt: "2026-10-03T00:00:00Z", updatedAt: "2026-10-03T00:00:00Z" }),
  project({ id: "b", name: "Atlas", status: "draft", createdAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-04T00:00:00Z" }),
  project({ id: "c", name: "Cargo", status: "design", runStopped: true, createdAt: "2026-10-02T00:00:00Z" }),
];
const ids = (list: Project[]) => list.map((p) => p.id);

/**
 * Eighty projects, and no way to find the ones at a phase or stopped, or to
 * order them other than by when they were made.
 */
describe("the projects listed", () => {
  it("are the newest first unless asked otherwise", () => {
    expect(ids(triage(all, { query: "", status: "all", sort: "newest" }))).toEqual(["a", "c", "b"]);
  });

  it("can be the recently updated first, or by name", () => {
    expect(ids(triage(all, { query: "", status: "all", sort: "updated" }))).toEqual(["b", "a", "c"]);
    expect(ids(triage(all, { query: "", status: "all", sort: "name" }))).toEqual(["b", "c", "a"]);
  });

  it("can be the ones in a phase, a draft counting as Requirements and Design", () => {
    expect(ids(triage(all, { query: "", status: "design", sort: "newest" }))).toEqual(["c", "b"]);
    expect(ids(triage(all, { query: "", status: "testing", sort: "newest" }))).toEqual(["a"]);
  });

  it("can be the ones whose run stopped, and still match the search", () => {
    expect(ids(triage(all, { query: "", status: "stopped", sort: "newest" }))).toEqual(["c"]);
    expect(ids(triage(all, { query: "LED", status: "all", sort: "newest" }))).toEqual(["a"]);
  });
});
