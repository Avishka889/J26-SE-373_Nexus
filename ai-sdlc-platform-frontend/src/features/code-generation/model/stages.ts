import type { StageChrome, StageMeta, StageSectionMeta } from "@/shared/ui/stage";
import { CODE_STAGE_IDS, type CodeStageId } from "@/types/project";

/**
 * How each code stage presents itself. Identity and order live in
 * `types/project` because `shared/` and `entities/` read them too; only the
 * words live here.
 *
 * Standard industry terms, spelled out. A reader who has built a web
 * application before should recognise every one of these without being told
 * what the platform calls it internally.
 */
export const CODE_STAGE_META: Record<CodeStageId, StageMeta> = {
  "sprint-scope": {
    label: "Sprint Scope",
    heading: "Sprint Scope",
    blurb: "Which stories this build covers, and the screens each one is traced to.",
  },
  "tech-stack": {
    label: "Tech Stack",
    heading: "Tech Stack",
    blurb: "Candidate stacks scored against counted facts from the design. You pick one.",
  },
  "api-contract": {
    label: "API Contract",
    heading: "API Contract",
    blurb:
      "The endpoints inferred from the screens and the architecture graph, by two arms you can compare.",
  },
  "frontend-code": {
    label: "Frontend Code",
    heading: "Frontend Code",
    blurb: "Pages, routes and a typed client, generated from the contract.",
  },
  "backend-code": {
    label: "Backend Code",
    heading: "Backend Code",
    blurb: "Models, routes and per endpoint contract tests, generated from the same contract.",
  },
  "contract-agreement": {
    label: "Contract Agreement",
    heading: "Contract Agreement",
    blurb:
      "Whether the generated code and the contract actually agree, checked by reading the code before any of it runs.",
  },
  build: {
    label: "Build",
    heading: "Build and Repository",
    blurb: "Install, typecheck and tests in a sandbox, then the push to GitHub.",
  },
  "code-review": {
    label: "Code Review",
    heading: "Code Review",
    blurb: "Everything above in one place, and the decision that starts Testing and Security.",
  },
};

/**
 * The blocks a stage is made of, in the order they appear.
 *
 * These are the anchor pills, and they double as the reader's position
 * indicator, so the list has to match what the stage actually renders. A stage
 * with one block gets no pills: a single anchor pointing at the whole page is
 * noise. The design phase learned that listing them out of order lights the
 * wrong pill on arrival, so these are written in render order.
 */
export const CODE_STAGE_SECTIONS: Record<CodeStageId, StageSectionMeta[]> = {
  "sprint-scope": [
    { id: "scope-summary", label: "Summary" },
    { id: "scope-stories", label: "Stories" },
    { id: "scope-next-sprint", label: "Next sprint" },
  ],
  "tech-stack": [
    { id: "stack-facts", label: "Facts" },
    { id: "stack-candidates", label: "Candidates" },
  ],
  "api-contract": [
    { id: "contract-arms", label: "Arms" },
    { id: "contract-endpoints", label: "Endpoints" },
    { id: "contract-diff", label: "Changes" },
  ],
  // One section: the file list is the whole stage, and a pill that scrolls the
  // reader to what is already in front of them is noise. The anchor row hides
  // itself below two sections.
  "frontend-code": [{ id: "frontend-files", label: "Files" }],
  "backend-code": [{ id: "backend-files", label: "Files" }],
  "contract-agreement": [
    { id: "agreement-counts", label: "Counts" },
    { id: "agreement-findings", label: "Findings" },
  ],
  build: [
    { id: "build-steps", label: "Steps" },
    { id: "build-repository", label: "Repository" },
    { id: "build-preview", label: "Preview" },
  ],
  "code-review": [
    { id: "review-summary", label: "Summary" },
    { id: "review-evidence", label: "Evidence" },
    { id: "review-decision", label: "Decision" },
  ],
};

/**
 * This phase's binding of the shared stage chrome.
 *
 * `versionNoun` is the one word that matters: the two phases version on
 * different axes, so a stage generated at code version 1 while the code is at
 * version 2 is outdated, and saying "requirements version" there would name
 * the wrong number entirely.
 */
export const CODE_CHROME: StageChrome<CodeStageId> = {
  ids: CODE_STAGE_IDS,
  meta: CODE_STAGE_META,
  sections: CODE_STAGE_SECTIONS,
  versionNoun: "code version",
  // From the C2 nodes. The scope and the stack read the design, which is
  // another phase; the code reads the contract, and the checks read the code.
  reads: {
    "api-contract": ["sprint-scope"],
    "frontend-code": ["api-contract", "sprint-scope"],
    "backend-code": ["api-contract"],
    "contract-agreement": ["api-contract", "frontend-code", "backend-code"],
    build: ["frontend-code", "backend-code"],
  },
};

export const codeStageIds = CODE_STAGE_IDS;

export function codeStageLabel(id: CodeStageId): string {
  return CODE_STAGE_META[id].label;
}

export function isCodeStageId(id: string): id is CodeStageId {
  return (CODE_STAGE_IDS as readonly string[]).includes(id);
}
