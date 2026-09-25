// Testing & Security phase - one coherent run.
//
// Every number in this file is derived from the same run: Sprint 24, Build 1852.
// 223 tests ran, 217 passed, 6 failed, 3 were skipped. The six failures are the
// six entries in the failure inbox, and the module table adds up to them.

import type { ConsoleLine, GreenRun, SuiteModule, TestingRun } from "./types";

export const testingRun: TestingRun = {
  sprint: "Sprint 24",
  build: 1852,
  branch: "main",
  startedAt: "2025-01-21 14:41",
  finishedAt: "2025-01-21 14:44",
  duration: "3m 12s",
  frontendRunner: "Vitest 2.1.4",
  backendRunner: "JUnit 5 · Gradle 8.7",
  lastVerified: {
    sprint: "Sprint 23",
    build: 1847,
    at: "2025-01-20 11:06",
    note: "211 tests, all passing",
  },
};

/* ========================================================================== *
 * 1 - Tests
 * ========================================================================== */

export const suiteModules: SuiteModule[] = [
  {
    id: "payments",
    name: "Payments",
    side: "backend",
    runner: "JUnit 5",
    passed: 68,
    failed: 3,
    skipped: 1,
    duration: "48s",
    requirements: ["US-101", "US-106"],
    failureIds: ["f1", "f2", "f3"],
  },
  {
    id: "kyc",
    name: "KYC",
    side: "backend",
    runner: "JUnit 5",
    passed: 41,
    failed: 1,
    skipped: 0,
    duration: "39s",
    requirements: ["US-103", "US-104"],
    failureIds: ["f4"],
  },
  {
    id: "auth",
    name: "Auth",
    side: "backend",
    runner: "JUnit 5",
    passed: 33,
    failed: 0,
    skipped: 1,
    duration: "31s",
    requirements: ["US-101"],
    failureIds: [],
  },
  {
    id: "notifications",
    name: "Notifications",
    side: "backend",
    runner: "JUnit 5",
    passed: 22,
    failed: 1,
    skipped: 0,
    duration: "18s",
    requirements: ["US-105"],
    failureIds: ["f5"],
  },
  {
    id: "payment-ui",
    name: "Payment UI",
    side: "frontend",
    runner: "Vitest",
    passed: 34,
    failed: 1,
    skipped: 1,
    duration: "9s",
    requirements: ["US-101", "US-103"],
    failureIds: ["f6"],
  },
  {
    id: "shared-ui",
    name: "Shared UI",
    side: "frontend",
    runner: "Vitest",
    passed: 19,
    failed: 0,
    skipped: 0,
    duration: "5s",
    requirements: ["US-106"],
    failureIds: [],
  },
];

export function suiteTotals(modules: SuiteModule[]) {
  const passed = modules.reduce((n, m) => n + m.passed, 0);
  const failed = modules.reduce((n, m) => n + m.failed, 0);
  const skipped = modules.reduce((n, m) => n + m.skipped, 0);
  const run = passed + failed;
  return { passed, failed, skipped, run, passRate: run === 0 ? 0 : (passed / run) * 100 };
}

export const runTranscript: ConsoleLine[] = [
  { kind: "cmd", text: "payflow test --all --coverage --mutation" },
  { kind: "info", text: `frontend · ${testingRun.frontendRunner}` },
  { kind: "pass", text: "src/__tests__/TransactionList.test.tsx · 19 tests · 5.0s" },
  { kind: "pass", text: "src/hooks/__tests__/usePayment.test.ts · 12 tests · 2.4s" },
  { kind: "fail", text: "src/__tests__/PaymentForm.test.tsx > shows a validation error for an expired card" },
  { kind: "detail", text: 'Unable to find text "Card expired" · PaymentForm.test.tsx:31' },
  { kind: "skip", text: "src/__tests__/PaymentForm.test.tsx > pays with a saved wallet · skipped, wallet API not wired" },
  { kind: "info", text: `backend · ${testingRun.backendRunner}` },
  { kind: "pass", text: "com.payflow.auth.AuthControllerTest · 33 tests · 31s" },
  { kind: "fail", text: "com.payflow.payments.PaymentControllerTest > shouldRefundPayment" },
  { kind: "detail", text: "expected status 200 but was 201 · PaymentControllerTest.java:46" },
  { kind: "fail", text: "com.payflow.payments.PaymentServiceTest > shouldSplitSettlementFees" },
  { kind: "detail", text: "no value present for feeBreakdown · PaymentServiceTest.java:33" },
  { kind: "fail", text: "com.payflow.payments.PaymentServiceTest > shouldRejectPaymentAboveKycLimit" },
  { kind: "detail", text: "expected KycRequiredException, nothing was thrown · PaymentServiceTest.java:51" },
  { kind: "fail", text: "com.payflow.kyc.KycServiceTest > shouldVerifyDocument" },
  { kind: "detail", text: "verify(document) was never called · KycServiceTest.java:28" },
  { kind: "fail", text: "com.payflow.notifications.NotificationServiceTest > shouldRetryFailedEmail" },
  { kind: "detail", text: "expected 3 delivery attempts but got 1 · NotificationServiceTest.java:31" },
  { kind: "summary", text: "223 tests run · 217 passed · 6 failed · 3 skipped · 3m 12s" },
  { kind: "muted", text: "line coverage 87.2% · branch coverage 74.1% · handing 6 failures to triage" },
];

/* ========================================================================== *
 * Running state - the transcript streams in this order
 * ========================================================================== */

export const streamingTranscript: ConsoleLine[] = [
  { kind: "cmd", text: "payflow test --all --coverage --mutation" },
  { kind: "muted", text: "resolving 223 tests from 8 files · Build 1852 · main" },
  { kind: "info", text: `frontend · ${testingRun.frontendRunner}` },
  { kind: "pass", text: "src/__tests__/TransactionList.test.tsx · 19 tests · 5.0s" },
  { kind: "pass", text: "src/hooks/__tests__/usePayment.test.ts · 12 tests · 2.4s" },
  { kind: "fail", text: "src/__tests__/PaymentForm.test.tsx > shows a validation error for an expired card" },
  { kind: "detail", text: 'Unable to find text "Card expired" · PaymentForm.test.tsx:31' },
  { kind: "skip", text: "src/__tests__/PaymentForm.test.tsx > pays with a saved wallet · skipped" },
  { kind: "info", text: `backend · ${testingRun.backendRunner}` },
  { kind: "pass", text: "com.payflow.auth.AuthControllerTest · 33 tests · 31s" },
  { kind: "fail", text: "com.payflow.payments.PaymentControllerTest > shouldRefundPayment" },
  { kind: "detail", text: "expected status 200 but was 201 · PaymentControllerTest.java:46" },
  { kind: "fail", text: "com.payflow.payments.PaymentServiceTest > shouldSplitSettlementFees" },
  { kind: "detail", text: "no value present for feeBreakdown · PaymentServiceTest.java:33" },
  { kind: "fail", text: "com.payflow.payments.PaymentServiceTest > shouldRejectPaymentAboveKycLimit" },
  { kind: "detail", text: "expected KycRequiredException, nothing was thrown · PaymentServiceTest.java:51" },
  { kind: "fail", text: "com.payflow.kyc.KycServiceTest > shouldVerifyDocument" },
  { kind: "detail", text: "verify(document) was never called · KycServiceTest.java:28" },
  { kind: "fail", text: "com.payflow.notifications.NotificationServiceTest > shouldRetryFailedEmail" },
  { kind: "detail", text: "expected 3 delivery attempts but got 1 · NotificationServiceTest.java:31" },
  { kind: "pass", text: "com.payflow.payments · 68 remaining tests · 48s" },
  { kind: "summary", text: "223 tests run · 217 passed · 6 failed · 3 skipped · 3m 12s" },
  { kind: "muted", text: "line coverage 87.2% · branch coverage 74.1% · handing 6 failures to triage" },
];

/* ========================================================================== *
 * The all-green run - a later build where every failure and finding is closed
 * ========================================================================== */

export const greenRun: GreenRun = {
  build: 1854,
  finishedAt: "2025-01-22 09:41",
  duration: "3m 04s",
  quality: {
    line: { percent: 93.4, covered: 7924, total: 8484 },
    branch: { percent: 84.2, covered: 2278, total: 2705 },
    mutation: { total: 312, killed: 301, survived: 11, score: 96 },
  },
  /** The two findings that had no proposal on Build 1852 got one before this build. */
  lateFixes: {
    v4: {
      language: "java" as const,
      summary: "Answer with a problem-details body and keep the trace in the server log.",
      before: `return ResponseEntity.status(500).body(ex.getStackTrace());`,
      after: `log.error("unhandled error, ref {}", ref, ex);
return ResponseEntity.status(500).body(new ProblemDetail(ref, "Something went wrong"));`,
    },
    v5: {
      language: "java" as const,
      summary: "Turn off DTDs and external entities on the parser factory.",
      before: `DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();`,
      after: `DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);`,
    },
  },
  transcript: [
    { kind: "cmd", text: "payflow test --all --coverage --mutation" },
    { kind: "info", text: `frontend · ${testingRun.frontendRunner}` },
    { kind: "pass", text: "src/__tests__/PaymentForm.test.tsx · 21 tests · 6.1s" },
    { kind: "pass", text: "src/__tests__/TransactionList.test.tsx · 19 tests · 5.0s" },
    { kind: "pass", text: "src/hooks/__tests__/usePayment.test.ts · 14 tests · 2.6s" },
    { kind: "info", text: `backend · ${testingRun.backendRunner}` },
    { kind: "pass", text: "com.payflow.auth.AuthControllerTest · 34 tests · 30s" },
    { kind: "pass", text: "com.payflow.payments · 72 tests · 47s" },
    { kind: "pass", text: "com.payflow.kyc.KycServiceTest · 42 tests · 38s" },
    { kind: "pass", text: "com.payflow.notifications.NotificationServiceTest · 23 tests · 18s" },
    { kind: "summary", text: "223 tests run · 223 passed · 0 failed · 0 skipped · 3m 04s" },
    { kind: "muted", text: "line coverage 93.4% · branch coverage 84.2% · nothing to triage" },
  ] as ConsoleLine[],
};

/** Progress the streaming console reports, line by line, for the summary strip. */
export const streamProgress: Record<number, { passed: number; failed: number }> = {
  3: { passed: 19, failed: 0 },
  4: { passed: 31, failed: 0 },
  5: { passed: 31, failed: 1 },
  9: { passed: 64, failed: 1 },
  10: { passed: 64, failed: 2 },
  12: { passed: 64, failed: 3 },
  14: { passed: 64, failed: 4 },
  16: { passed: 105, failed: 5 },
  18: { passed: 127, failed: 6 },
  20: { passed: 217, failed: 6 },
};
