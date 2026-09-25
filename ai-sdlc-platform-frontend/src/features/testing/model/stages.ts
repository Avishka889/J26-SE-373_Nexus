import type { StageChrome, StageMeta, StageSectionMeta } from "@/shared/ui/stage";
import { TEST_STAGE_IDS, type TestStageId } from "@/types/project";

/**
 * How each testing stage presents itself.
 *
 * Identity and order live in `types/project`, generated from the contract, so
 * this file holds only the words. That is the point of writing it at all: the
 * phase used to keep six step ids of its own invention over the server's seven
 * stages, which meant the stepper and the stage table could disagree and one of
 * them, test generation, had no place on screen to report anything.
 *
 * Standard industry terms. A reader who has run a test suite and a scanner
 * before should recognise every one of these without being told what the
 * platform calls it internally.
 */
export const TEST_STAGE_META: Record<TestStageId, StageMeta> = {
  "test-generation": {
    label: "Test Generation",
    heading: "Test Generation",
    blurb:
      "Tests written from the acceptance criteria and the API contract, and the obligations nothing can cover.",
  },
  "test-run": {
    label: "Test Run",
    heading: "Test Run",
    blurb: "The suite executed in a sandbox, reported as it happened.",
  },
  "test-quality": {
    label: "Test Quality",
    heading: "Test Quality",
    blurb:
      "Coverage, and whether the tests notice a deliberately broken program. A green suite that kills no mutant is not a safety net.",
  },
  "self-healing": {
    label: "Self Healing",
    heading: "Self Healing",
    blurb:
      "Every failure classified before anything is repaired, and every repair made to prove itself. A regression is flagged, never healed.",
  },
  "security-scan": {
    label: "Security",
    heading: "Security Scan",
    blurb:
      "Findings from every detector, each with evidence that resolves in the repository and a severity from the rule table.",
  },
  remediation: {
    label: "Remediation",
    heading: "Remediation and Re-verification",
    blurb:
      "Fixes proposed for findings whose evidence resolves, and what the numbers said after one was applied.",
  },
  "test-review": {
    label: "Test Review",
    heading: "Test Review",
    blurb: "Everything above in one place, and the decision that lets this version move on.",
  },
};

/**
 * The blocks each stage is made of, in render order.
 *
 * These are the anchor pills and they double as the reader's position
 * indicator, so the list has to match what the stage actually renders, in the
 * order it renders them. A stage with one block gets no pills: a single anchor
 * pointing at the whole page is noise, and the anchor row hides itself below
 * two sections.
 */
export const TEST_STAGE_SECTIONS: Record<TestStageId, StageSectionMeta[]> = {
  "test-generation": [
    { id: "generation-counts", label: "What was written" },
    { id: "generation-gaps", label: "What nothing covers" },
  ],
  // "Failures" named a section with no failure in it: the suite's results,
  // the transcript and the test files, all three under one pill. The failures
  // are in Self Healing. The id stays, since the address may carry it.
  "test-run": [
    { id: "run-summary", label: "Summary" },
    { id: "run-failures", label: "Results" },
    { id: "run-transcript", label: "Transcript" },
    { id: "run-files", label: "Test files" },
  ],
  // One block each, so no pills: the coverage chart, the failure inbox and the
  // proof pairs are each a single thing, and an anchor pointing at what is
  // already in front of the reader is noise.
  "test-quality": [{ id: "quality-summary", label: "Quality" }],
  "self-healing": [{ id: "healing-inbox", label: "Failures" }],
  remediation: [{ id: "remediation-fixes", label: "Fixes" }],
  "security-scan": [
    { id: "security-counts", label: "By severity" },
    { id: "security-findings", label: "Findings" },
    { id: "security-detectors", label: "Detectors" },
  ],
  // The audit log is no longer a section: the review links to the Activity
  // Log, which is the same entries. And the second pill is named for what it
  // opens, which was never a list of decisions.
  "test-review": [
    { id: "review-summary", label: "Summary" },
    { id: "review-decision", label: "After you approve" },
  ],
};

/**
 * This phase's binding of the shared stage chrome.
 *
 * `versionNoun` is the word that decides whether a staleness message names the
 * right number. This phase versions on its own test axis and watches the code
 * axis, so "code version" here would name the thing it is measured against
 * rather than the thing it produced.
 */
export const TEST_CHROME: StageChrome<TestStageId> = {
  ids: TEST_STAGE_IDS,
  meta: TEST_STAGE_META,
  sections: TEST_STAGE_SECTIONS,
  versionNoun: "test version",
  // From the C3 nodes. Generation and the scan read the code, which is another
  // phase; quality and healing read the run, and remediation reads the scan.
  reads: {
    "test-run": ["test-generation"],
    "test-quality": ["test-run"],
    "self-healing": ["test-run"],
    remediation: ["security-scan"],
  },
};

/**
 * The chrome for a page with or without the detector comparison.
 *
 * Only the demo has that table, and the live page kept its "Detectors" pill,
 * which scrolled to nothing.
 */
export function testChromeFor(hasDetectorComparison: boolean): StageChrome<TestStageId> {
  if (hasDetectorComparison) return TEST_CHROME;
  return {
    ...TEST_CHROME,
    sections: {
      ...TEST_STAGE_SECTIONS,
      "security-scan": TEST_STAGE_SECTIONS["security-scan"].filter(
        (section) => section.id !== "security-detectors",
      ),
    },
  };
}

export function testStageLabel(id: TestStageId): string {
  return TEST_STAGE_META[id].label;
}
