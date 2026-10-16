/**
 * The demo content the Testing workspace renders today, and only that.
 *
 * **This is not the API seam.** The seam is `api/createTestingApi.ts`, which
 * speaks the `TestSnapshot` the orchestrator really returns. This module holds
 * the hand written demo data the page's components still read, in a vocabulary
 * of their own (`SuiteModule`, `FailureItem`, `Finding`) that predates the
 * contracts.
 *
 * It is named legacy because it is on the way out, not because it is wrong. The
 * components derive everything through `model/view.ts`, so migrating them is a
 * matter of re-sourcing that one derivation from `TestSnapshot` rather than
 * touching twenty five files. Until that happens this keeps the workspace
 * working, and the live flag must stay off: the server does not return this
 * shape and never did.
 *
 * What used to be here and is gone: an HTTP client calling seven routes that do
 * not exist on the orchestrator. It made the demo look wired and could not have
 * answered once.
 */

import type { FileEntry } from "@/shared/code-viewer/buildFileTree";
import { auditTrail, decisionChain } from "./audit";
import {
  appliedFixes,
  detectorComparison,
  detectorNames,
  findings,
  severityOrder,
} from "./findings";
import { failures, testFileContents, testFileMeta, testFiles } from "./failures";
import { quality } from "./quality";
import {
  greenRun,
  runTranscript,
  streamProgress,
  streamingTranscript,
  suiteModules,
  testingRun,
} from "./runs";
import type {
  AppliedFix,
  AuditEntry,
  ConsoleLine,
  DecisionChainStep,
  Detector,
  DetectorComparison,
  FailureItem,
  Finding,
  GreenRun,
  Quality,
  Severity,
  SuiteModule,
  TestFileMeta,
  TestingRun,
} from "./types";

const FIXTURE_DELAY_MS = 120;

export type TestingRunPayload = {
  run: TestingRun;
  modules: SuiteModule[];
  transcript: ConsoleLine[];
  streamingTranscript: ConsoleLine[];
  streamProgress: Record<number, { passed: number; failed: number }>;
  greenRun: GreenRun;
};

export type TestingFailuresPayload = {
  failures: FailureItem[];
};

export type TestingFindingsPayload = {
  findings: Finding[];
  appliedFixes: AppliedFix[];
  severityOrder: Severity[];
  detectorNames: Record<Detector, string>;
  detectorComparison: DetectorComparison;
};

export type TestingQualityPayload = {
  quality: Quality;
};

export type TestingAuditPayload = {
  auditTrail: AuditEntry[];
  decisionChain: DecisionChainStep[];
};

export type TestingTestFilesPayload = {
  files: FileEntry[];
  meta: Record<string, TestFileMeta>;
  contents: Record<string, string>;
};

/** Full phase payload used by the demo page + buildView. */
export type TestingSnapshot = TestingRunPayload &
  TestingFailuresPayload &
  TestingFindingsPayload &
  TestingQualityPayload &
  TestingAuditPayload & {
    testFiles: FileEntry[];
    testFileMeta: Record<string, TestFileMeta>;
    testFileContents: Record<string, string>;
  };

export interface TestingDemoApi {
  getSnapshot(projectId: string): Promise<TestingSnapshot>;
  getRun(projectId: string): Promise<TestingRunPayload>;
  getFailures(projectId: string): Promise<TestingFailuresPayload>;
  getFindings(projectId: string): Promise<TestingFindingsPayload>;
  getQuality(projectId: string): Promise<TestingQualityPayload>;
  getAudit(projectId: string): Promise<TestingAuditPayload>;
  getTestFiles(projectId: string): Promise<TestingTestFilesPayload>;
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

/** Sync fixture snapshot for the demo page (no network). */
export function getTestingSnapshot(): TestingSnapshot {
  return {
    run: structuredClone(testingRun),
    modules: structuredClone(suiteModules),
    transcript: structuredClone(runTranscript),
    streamingTranscript: structuredClone(streamingTranscript),
    streamProgress: structuredClone(streamProgress),
    greenRun: structuredClone(greenRun),
    failures: structuredClone(failures),
    findings: structuredClone(findings),
    appliedFixes: structuredClone(appliedFixes),
    severityOrder: [...severityOrder],
    detectorNames: { ...detectorNames },
    detectorComparison: structuredClone(detectorComparison),
    quality: structuredClone(quality),
    auditTrail: structuredClone(auditTrail),
    decisionChain: structuredClone(decisionChain),
    testFiles: structuredClone(testFiles),
    testFileMeta: structuredClone(testFileMeta),
    testFileContents: structuredClone(testFileContents),
  };
}

function createFixtureTestingApi(): TestingDemoApi {
  return {
    async getSnapshot(_projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return getTestingSnapshot();
    },
    async getRun(_projectId) {
      await sleep(FIXTURE_DELAY_MS);
      const snap = getTestingSnapshot();
      return {
        run: snap.run,
        modules: snap.modules,
        transcript: snap.transcript,
        streamingTranscript: snap.streamingTranscript,
        streamProgress: snap.streamProgress,
        greenRun: snap.greenRun,
      };
    },
    async getFailures(_projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return { failures: structuredClone(failures) };
    },
    async getFindings(_projectId) {
      await sleep(FIXTURE_DELAY_MS);
      const snap = getTestingSnapshot();
      return {
        findings: snap.findings,
        appliedFixes: snap.appliedFixes,
        severityOrder: snap.severityOrder,
        detectorNames: snap.detectorNames,
        detectorComparison: snap.detectorComparison,
      };
    },
    async getQuality(_projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return { quality: structuredClone(quality) };
    },
    async getAudit(_projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return {
        auditTrail: structuredClone(auditTrail),
        decisionChain: structuredClone(decisionChain),
      };
    },
    async getTestFiles(_projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return {
        files: structuredClone(testFiles),
        meta: structuredClone(testFileMeta),
        contents: structuredClone(testFileContents),
      };
    },
  };
}

export function createTestingDemoApi(): TestingDemoApi {
  return createFixtureTestingApi();
}

export const testingDemoApi: TestingDemoApi = createTestingDemoApi();
