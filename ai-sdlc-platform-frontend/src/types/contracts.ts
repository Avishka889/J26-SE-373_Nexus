/**
 * Re-export generated contract types when `@sdlc/contracts-ts` (or equivalent) is available.
 * Until then, UI and feature modules import domain DTOs from here so the swap is a single edit.
 */

export type ContractId = string;

export type {
  DesignStageId,
  Project,
  ProjectStatus,
  ReqPhase,
  RequirementChatMessage,
  RequirementChatRole,
  RequirementChatType,
  TestStageId,
} from "./project";

export { DESIGN_STAGE_IDS, TEST_STAGE_IDS } from "./project";

export type { SettingsState } from "./settings";

/** Placeholder run identifiers used by testing / orchestrator seams. */
export type RunId = ContractId;
export type ValidationReportId = ContractId;
