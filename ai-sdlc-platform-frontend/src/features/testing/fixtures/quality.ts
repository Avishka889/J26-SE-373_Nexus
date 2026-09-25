import type { Quality } from "./types";

/* ========================================================================== *
 * 3 - Quality
 * ========================================================================== */

export const quality: Quality = {
  line: { percent: 87.2, covered: 7344, total: 8424 },
  branch: { percent: 74.1, covered: 1982, total: 2674 },
  mutation: { total: 312, killed: 284, survived: 28, score: 91 },
  tool: "PIT 1.16 · Stryker 8.6",
  byModule: [
    { name: "payments/PaymentService.java", line: 94, branch: 82, covered: 1512, total: 1608 },
    { name: "payments/PaymentController.java", line: 91, branch: 78, covered: 782, total: 859 },
    { name: "auth/AuthService.java", line: 89, branch: 74, covered: 1104, total: 1240 },
    { name: "components/PaymentForm.tsx", line: 92, branch: 80, covered: 664, total: 722 },
    { name: "hooks/usePayment.ts", line: 85, branch: 70, covered: 289, total: 340 },
    { name: "kyc/KycService.java", line: 76, branch: 61, covered: 918, total: 1208 },
    { name: "notifications/NotificationService.java", line: 68, branch: 52, covered: 574, total: 844 },
  ],
  survivors: [
    {
      location: "notifications/NotificationService.java:118",
      change: "attempts >= maxAttempts became attempts > maxAttempts",
      note: "One extra delivery attempt, and no test noticed.",
    },
    {
      location: "kyc/KycService.java:64",
      change: "removed the expiry check on the document date",
      note: "An expired passport would verify, and no test noticed.",
    },
    {
      location: "hooks/usePayment.ts:41",
      change: "swallowed the error instead of re-throwing it",
      note: "A declined card would look like a success, and no test noticed.",
    },
  ],
  trend: [
    { build: 1846, line: 78, branch: 64 },
    { build: 1847, line: 79, branch: 66 },
    { build: 1848, line: 81, branch: 68 },
    { build: 1849, line: 82, branch: 69 },
    { build: 1851, line: 85, branch: 72 },
    { build: 1852, line: 87, branch: 74 },
  ],
  trendNote: "Build 1850 failed to compile, so it recorded no coverage.",
};
