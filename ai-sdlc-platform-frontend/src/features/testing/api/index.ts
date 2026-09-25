/**
 * The Testing and Security seam.
 *
 * `createTestingApi` is the real one: fixtures or the orchestrator, both
 * answering with the `TestSnapshot` the schema generates.
 *
 * The demo exports below serve the workspace's components until their
 * derivation is re-sourced from that snapshot. They are re-exported here
 * rather than imported from `fixtures/` directly so that the day they go, they
 * go from one place.
 */

export { createTestingApi, testingApi } from "./createTestingApi";
export type {
  FindingDecisionInput,
  HealDecisionInput,
  ProposalDecisionInput,
  TestDecisionInput,
  TestSnapshot,
  TestStages,
  TestingApi,
} from "./types";

export {
  createTestingDemoApi,
  getTestingSnapshot,
  testingDemoApi,
  type TestingAuditPayload,
  type TestingDemoApi,
  type TestingFailuresPayload,
  type TestingFindingsPayload,
  type TestingQualityPayload,
  type TestingRunPayload,
  type TestingSnapshot,
  type TestingTestFilesPayload,
} from "../fixtures/legacyDemo";
