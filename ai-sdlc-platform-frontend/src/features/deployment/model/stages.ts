import type { StageChrome, StageMeta, StageSectionMeta } from "@/shared/ui/stage";
import { DEPLOY_STAGE_IDS, type DeployStageId } from "@/types/project";

/**
 * How each deployment stage presents itself.
 *
 * Identity and order live in `types/project`, checked against the contract, so
 * this file holds only the words. Standard industry terms: a reader who has
 * shipped a service before should recognise every one of them without being
 * told what the platform calls it internally.
 */
export const DEPLOY_STAGE_META: Record<DeployStageId, StageMeta> = {
  "dependency-updates": {
    label: "Dependency Updates",
    heading: "Dependency Updates",
    blurb:
      "Newer releases of the project's dependencies, found in their registries, and the ones that could not be assessed and why.",
  },
  "changelog-analysis": {
    label: "Changelog Analysis",
    heading: "Changelog Analysis",
    blurb:
      "What each update's release notes say. A model reads them, and a claim is kept only when its quote is really in the notes.",
  },
  "impact-analysis": {
    label: "Impact Analysis",
    heading: "Impact Analysis",
    blurb:
      "Where this project uses what each update changes, traced to files and to the Semantic Architecture Graph.",
  },
  "risk-assessment": {
    label: "Risk Assessment",
    heading: "Risk Assessment",
    blurb:
      "Three signals per update and the most cautious level any of them gives. The level is the rule's, never a model's.",
  },
  "pipeline-generation": {
    label: "CI/CD Pipeline",
    heading: "CI/CD Pipeline",
    blurb:
      "The workflow, container and hosting files this release needs, generated from validated templates and checked before anything runs.",
  },
  "staging-verification": {
    label: "Staging",
    heading: "Staging Verification",
    blurb:
      "The release candidate built and started in a container, and checked the way production will be: fingerprint, health and smoke requests.",
  },
  "rollback-planning": {
    label: "Rollback Plan",
    heading: "Rollback Plan",
    blurb:
      "The verified release a rollback would restore, the steps to it, and how restored is proved rather than assumed.",
  },
  "deployment-review": {
    label: "Deployment Review",
    heading: "Deployment Review",
    blurb:
      "Everything above in one place, the decision each update needs, and the one that lets this release go.",
  },
  release: {
    label: "Release",
    heading: "Production Release",
    blurb:
      "The release carried out step by step, every attempt recorded with its cause. A rollback starts only when a person approves it.",
  },
  monitoring: {
    label: "Monitoring",
    heading: "Monitoring",
    blurb:
      "The release that serves now, watched for a bounded window, and what that suggests the next requirements should say.",
  },
};

/**
 * The blocks each stage is made of, in render order.
 *
 * These are the anchor pills and the reader's position indicator, so the list
 * has to match what the stage renders, in the order it renders them.
 */
export const DEPLOY_STAGE_SECTIONS: Record<DeployStageId, StageSectionMeta[]> = {
  "dependency-updates": [
    { id: "updates-checked", label: "What was checked" },
    { id: "updates-available", label: "Available updates" },
    { id: "updates-rejected", label: "Could not assess" },
  ],
  "changelog-analysis": [
    { id: "changelog-claims", label: "Claims" },
    { id: "changelog-refused", label: "Refused claims" },
  ],
  "impact-analysis": [
    { id: "impact-components", label: "Affected components" },
    { id: "impact-files", label: "Affected files" },
    { id: "impact-unmapped", label: "Not mapped" },
  ],
  "risk-assessment": [
    { id: "risk-levels", label: "By risk level" },
    { id: "risk-updates", label: "Updates and evidence" },
    { id: "risk-disagreements", label: "Where signals disagree" },
  ],
  "pipeline-generation": [
    { id: "pipeline-layout", label: "Detected layout" },
    { id: "pipeline-files", label: "Generated files" },
    { id: "pipeline-validation", label: "Validation" },
  ],
  "staging-verification": [
    { id: "staging-steps", label: "Verification steps" },
    { id: "staging-console", label: "Console" },
  ],
  "rollback-planning": [
    { id: "rollback-target", label: "Restore target" },
    { id: "rollback-steps", label: "Steps and checks" },
  ],
  "deployment-review": [
    { id: "review-summary", label: "Summary" },
    { id: "review-decisions", label: "Decisions" },
    { id: "review-audit", label: "Audit" },
  ],
  release: [
    { id: "release-deployment", label: "Deployment" },
    { id: "release-console", label: "Console" },
    { id: "release-history", label: "History" },
  ],
  monitoring: [
    { id: "monitoring-health", label: "Health" },
    { id: "monitoring-events", label: "Events" },
    { id: "monitoring-feedback", label: "Feedback for requirements" },
  ],
};

/**
 * This phase's binding of the shared stage chrome.
 *
 * The phase versions on its own deploy axis, so a staleness message names the
 * deploy version rather than the code or test version it was measured against.
 */
export const DEPLOY_CHROME: StageChrome<DeployStageId> = {
  ids: DEPLOY_STAGE_IDS,
  meta: DEPLOY_STAGE_META,
  sections: DEPLOY_STAGE_SECTIONS,
  versionNoun: "deploy version",
  // From the C4 nodes: a changelog retried while the review waited left the
  // risk levels computed from the vote it replaced.
  reads: {
    "changelog-analysis": ["dependency-updates"],
    "impact-analysis": ["dependency-updates", "changelog-analysis"],
    "risk-assessment": ["dependency-updates", "changelog-analysis", "impact-analysis"],
    "pipeline-generation": ["risk-assessment", "dependency-updates"],
    "staging-verification": ["pipeline-generation", "risk-assessment", "dependency-updates"],
    "rollback-planning": ["staging-verification", "risk-assessment"],
  },
};

export function deployStageLabel(id: DeployStageId): string {
  return DEPLOY_STAGE_META[id].label;
}
