/**
 * The Deployment seam.
 *
 * `createDeploymentApi` answers with the `DeploySnapshot` the schema generates,
 * from the fixtures or the orchestrator.
 */

export { createDeploymentApi, deploymentApi } from "./createDeploymentApi";
export type {
  DeployDecisionInput,
  DeployFile,
  DeploySnapshot,
  DeployStages,
  DeploymentApi,
  FeedbackDecisionInput,
  MonitoringWindowInput,
  PolicyInput,
  ReleaseTarget,
  ReleaseTargetOption,
  RiskLevel,
  RollbackDecisionInput,
  UpdateDecisionInput,
} from "./types";
