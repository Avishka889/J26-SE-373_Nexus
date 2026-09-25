import type { AppliedFix, Detector, DetectorComparison, Finding, Severity } from "./types";

/* ========================================================================== *
 * 4 - Security
 * ========================================================================== */

export const findings: Finding[] = [
  {
    id: "v1",
    cwe: "CWE-79",
    name: "Cross-site scripting",
    severity: "high",
    cvss: 7.4,
    file: "backend/src/main/java/com/payflow/payments/PaymentController.java",
    line: 42,
    status: "fix-proposed",
    foundBy: ["local", "reviewer"],
    explanation:
      "The payment description a customer types is written straight into the confirmation email template. A description containing a script tag is rendered as markup when the customer opens that email in a browser client.",
    fix: {
      language: "java",
      summary: "Escape the description before it reaches the template.",
      before: `model.addAttribute("description", request.getDescription());
return new ModelAndView("email/receipt", model.asMap());`,
      after: `model.addAttribute("description", HtmlUtils.htmlEscape(request.getDescription()));
return new ModelAndView("email/receipt", model.asMap());`,
    },
  },
  {
    id: "v2",
    cwe: "CWE-89",
    name: "SQL injection",
    severity: "critical",
    cvss: 9.1,
    file: "backend/src/main/java/com/payflow/user/UserRepository.java",
    line: 88,
    status: "verified",
    foundBy: ["local", "reviewer"],
    explanation:
      "The customer lookup builds its SQL by concatenating the email argument, so an email of ' OR '1'='1 returns every row in the users table. The address comes from an unauthenticated password-reset form.",
    fix: {
      language: "java",
      summary: "Send the email as a parameter instead of pasting it into the statement.",
      before: `String sql = "SELECT * FROM users WHERE email = '" + email + "'";
return jdbcTemplate.query(sql, userRowMapper);`,
      after: `String sql = "SELECT * FROM users WHERE email = ?";
return jdbcTemplate.query(sql, userRowMapper, email);`,
    },
  },
  {
    id: "v3",
    cwe: "CWE-352",
    name: "Cross-site request forgery",
    severity: "medium",
    cvss: 5.2,
    file: "backend/src/main/java/com/payflow/auth/AuthController.java",
    line: 31,
    status: "verified",
    foundBy: ["local"],
    explanation:
      "The session refresh endpoint accepts a POST with no CSRF token, so any other site a signed-in customer visits can keep their session alive in the background.",
    fix: {
      language: "java",
      summary: "Turn CSRF protection back on for the auth chain.",
      before: `http.csrf(csrf -> csrf.disable())
    .authorizeHttpRequests(auth -> auth.requestMatchers("/api/v1/auth/**").permitAll());`,
      after: `http.csrf(csrf -> csrf.csrfTokenRepository(CookieCsrfTokenRepository.withHttpOnlyFalse()))
    .authorizeHttpRequests(auth -> auth.requestMatchers("/api/v1/auth/**").permitAll());`,
    },
  },
  {
    id: "v4",
    cwe: "CWE-200",
    name: "Information exposure",
    severity: "medium",
    cvss: 4.8,
    file: "backend/src/main/java/com/payflow/support/ErrorHandler.java",
    line: 15,
    status: "open",
    foundBy: ["reviewer"],
    explanation:
      "The global error handler returns the stack trace in the response body. It names internal classes, the ORM, and the database driver version, which tells an attacker what to aim at.",
    openReason:
      "No fix proposed yet. This handler shapes the error response for every endpoint, so the replacement needs an owner's decision on what clients get instead.",
  },
  {
    id: "v5",
    cwe: "CWE-611",
    name: "XML external entity",
    severity: "low",
    cvss: 3.1,
    file: "backend/src/main/java/com/payflow/settlement/XmlParser.java",
    line: 22,
    status: "open",
    foundBy: ["local"],
    explanation:
      "The settlement file parser resolves external entities, so a crafted bank file can make the server read a local file or call out to another host. Files arrive from one trusted bank over SFTP, which is why this is scored low.",
    openReason: "No fix proposed yet. Waiting on the settlement owner to confirm no bank file relies on entity expansion.",
  },
  {
    id: "v6",
    cwe: "CWE-502",
    name: "Unsafe deserialization",
    severity: "critical",
    cvss: 8.8,
    file: "backend/src/main/java/com/payflow/auth/SessionManager.java",
    line: 67,
    status: "re-verifying",
    foundBy: ["local", "reviewer"],
    explanation:
      "Session data from the cookie is read with Java's native ObjectInputStream. A crafted cookie can construct arbitrary objects while it is being read, which is remote code execution before any of our own code runs.",
    fix: {
      language: "java",
      summary: "Read the session as JSON with a fixed type instead of a native object stream.",
      before: `ObjectInputStream in = new ObjectInputStream(new ByteArrayInputStream(bytes));
return (Session) in.readObject();`,
      after: `return sessionJson.readValue(bytes, Session.class);
// sessionJson: ObjectMapper with default typing disabled`,
    },
  },
];

export const severityOrder: Severity[] = ["critical", "high", "medium", "low"];

export const detectorNames: Record<Detector, string> = {
  local: "Local model",
  reviewer: "AI reviewer",
};

/** Model-level numbers from the offline evaluation set - not per-finding confidence. */
export const detectorComparison: DetectorComparison = {
  caption:
    "Measured on 1,240 labelled Java and TypeScript files on 14 Jan 2025. These are model-level numbers for the detectors, not confidence in any single finding.",
  rows: [
    { detector: "Local model", precision: 0.89, recall: 0.84, f1: 0.86, cost: "$0.00", latency: "0.4s", offline: true },
    { detector: "AI reviewer", precision: 0.92, recall: 0.9, f1: 0.91, cost: "$0.31", latency: "6.2s", offline: false },
    { detector: "Both, combined", precision: 0.94, recall: 0.96, f1: 0.95, cost: "$0.31", latency: "6.6s", offline: false },
  ],
};

/* ========================================================================== *
 * 5 - Fix and re-verify: two proofs per applied fix
 * ========================================================================== */

export const appliedFixes: AppliedFix[] = [
  {
    findingId: "v2",
    appliedBy: "S. Patel",
    appliedAt: "2025-01-21 15:02",
    scan: {
      state: "pass",
      at: "15:04",
      detail: "1,412 files re-scanned · CWE-89 no longer reported at UserRepository.java:88 · no new findings",
    },
    suite: {
      state: "pass",
      at: "15:09",
      detail: "223 tests run · 217 passed · 6 failed · the same 6 as before the fix, no new failures",
    },
    verdict: "Fixed and re-verified.",
  },
  {
    findingId: "v3",
    appliedBy: "S. Patel",
    appliedAt: "2025-01-21 15:05",
    scan: {
      state: "pass",
      at: "15:07",
      detail: "1,412 files re-scanned · CWE-352 no longer reported at AuthController.java:31 · no new findings",
    },
    suite: {
      state: "pass",
      at: "15:11",
      detail: "223 tests run · 217 passed · 6 failed · the same 6 as before the fix, no new failures",
    },
    verdict: "Fixed and re-verified.",
  },
  {
    findingId: "v6",
    appliedBy: "A. Chen",
    appliedAt: "2025-01-21 15:14",
    scan: {
      state: "pass",
      at: "15:16",
      detail: "1,412 files re-scanned · CWE-502 no longer reported at SessionManager.java:67 · no new findings",
    },
    suite: {
      state: "running",
      detail: "148 of 223 tests run",
    },
    verdict: "Not verified yet - waiting on the suite re-run.",
  },
];
