import type { FileEntry } from "@/shared/code-viewer/buildFileTree";
import type { FailureItem, TestFileMeta } from "./types";

/* ========================================================================== *
 * 2 - Healing: the failure inbox is the only approval queue
 * ========================================================================== */

export const failures: FailureItem[] = [
  {
    id: "f1",
    test: "PaymentControllerTest.shouldRefundPayment",
    moduleId: "payments",
    runner: "JUnit 5",
    triage: "brittle",
    state: "awaiting-approval",
    reason: "Expected status 200 but got 201",
    age: "13 min ago",
    at: "2025-01-21 14:43",
    build: 1852,
    requirement: { id: "US-101", title: "As a user, I want to add a credit card" },
    file: "backend/src/test/java/com/payflow/payments/PaymentControllerTest.java",
    line: 46,
    repair: {
      proposedAt: "2025-01-21 14:46",
      language: "java",
      original: `@Test
void shouldRefundPayment() throws Exception {
    Payment payment = seedCapturedPayment();

    mockMvc.perform(post("/api/v1/payments/{id}/refund", payment.getId()))
        .andExpect(status().isOk());
}`,
      proposed: `@Test
void shouldRefundPayment() throws Exception {
    Payment payment = seedCapturedPayment();

    mockMvc.perform(post("/api/v1/payments/{id}/refund", payment.getId()))
        .andExpect(status().isCreated())
        .andExpect(jsonPath("$.status").value("REFUNDED"))
        .andExpect(jsonPath("$.refundId").isNotEmpty());
}`,
      guard: {
        unchanged: { pass: true, detail: "Ran the repaired test against today's code · 1 test · 1 passed" },
        planted: {
          pass: true,
          detail: "Planted a bug that answers 201 with an empty body · 1 test · 1 failed · caught",
        },
      },
      verdictLine: "Repair holds. It still catches the planted bug.",
      why: "Refunds used to update the payment in place. They now create a refund record, so the endpoint answers 201 Created and returns a refund id. The test only ever checked the status code, so it went stale the moment the endpoint changed shape. The repair checks the new code and the two fields the endpoint promises.",
    },
  },
  {
    id: "f2",
    test: "PaymentServiceTest.shouldSplitSettlementFees",
    moduleId: "payments",
    runner: "JUnit 5",
    triage: "brittle",
    state: "awaiting-approval",
    reason: "No value present for feeBreakdown",
    age: "13 min ago",
    at: "2025-01-21 14:43",
    build: 1852,
    requirement: { id: "US-106", title: "As a user, I want to view transaction history" },
    file: "backend/src/test/java/com/payflow/payments/PaymentServiceTest.java",
    line: 33,
    repair: {
      proposedAt: "2025-01-21 14:47",
      language: "java",
      original: `@Test
void shouldSplitSettlementFees() {
    Payment payment = paymentService.capture(request(12_000L, "USD"));

    FeeBreakdown fees = payment.getFeeBreakdown();
    assertEquals(348L, fees.platformFee());
}`,
      proposed: `@Test
void shouldSplitSettlementFees() {
    Payment payment = paymentService.capture(request(12_000L, "USD"));

    FeeBreakdown fees = payment.feeBreakdown()
        .orElseThrow(() -> new AssertionError("captured payment has no fees"));
    assertEquals(348L, fees.platformFee());
    assertEquals(11_652L, fees.netToMerchant());
}`,
      guard: {
        unchanged: { pass: true, detail: "Ran the repaired test against today's code · 1 test · 1 passed" },
        planted: {
          pass: true,
          detail: "Planted a bug that keeps the platform fee and zeroes the merchant's net · 1 test · 1 failed · caught",
        },
      },
      verdictLine: "Repair holds. It still catches the planted bug.",
      why: "getFeeBreakdown() became feeBreakdown() and returns an Optional now, so the old call no longer compiles. The repair unwraps it with a message that says what went wrong, and also checks the merchant's net amount - a number the old test never looked at.",
    },
  },
  {
    id: "f3",
    test: "PaymentServiceTest.shouldRejectPaymentAboveKycLimit",
    moduleId: "payments",
    runner: "JUnit 5",
    triage: "regression",
    state: "escalated",
    reason: "Expected KycRequiredException, nothing was thrown",
    age: "13 min ago",
    at: "2025-01-21 14:43",
    build: 1852,
    requirement: { id: "US-103", title: "As a user, I want to verify my identity" },
    file: "backend/src/test/java/com/payflow/payments/PaymentServiceTest.java",
    line: 51,
    owner: "M. Rodriguez",
    note: "A $1,400 payment from an unverified customer went through. The KYC check moved behind a feature flag in Build 1851 and the flag is off in this environment, so the rule is not being applied. The test is correct and was left untouched - this is a real regression, routed to M. Rodriguez.",
  },
  {
    id: "f4",
    test: "KycServiceTest.shouldVerifyDocument",
    moduleId: "kyc",
    runner: "JUnit 5",
    triage: "brittle",
    state: "blocked",
    reason: "verify(document) was never called",
    age: "13 min ago",
    at: "2025-01-21 14:43",
    build: 1852,
    requirement: { id: "US-103", title: "As a user, I want to verify my identity" },
    file: "backend/src/test/java/com/payflow/kyc/KycServiceTest.java",
    line: 28,
    owner: "A. Chen",
    repair: {
      proposedAt: "2025-01-21 14:47",
      language: "java",
      original: `@Test
void shouldVerifyDocument() {
    kycService.verify(document);

    verify(documentVerifier).verify(document);
}`,
      proposed: `@Test
void shouldVerifyDocument() {
    kycService.verify(document);

    verify(documentVerifier).verify(document, VerificationContext.DEFAULT);
}`,
      guard: {
        unchanged: { pass: true, detail: "Ran the repaired test against today's code · 1 test · 1 passed" },
        planted: {
          pass: false,
          detail: "Planted a bug that returns UNVERIFIED for a valid document · 1 test · 1 passed · the bug went through",
        },
      },
      verdictLine: "Repair rejected. It no longer catches a planted bug, so it would hide the failure instead of reporting it.",
      why: "verify() takes a verification context now, so the old call no longer matches and the test fails to compile. The repair fixes the call - but it only checks that the verifier was called, not what it answered. A service that accepted an unverified document would still pass. Escalated to A. Chen with the proposal attached.",
    },
  },
  {
    id: "f5",
    test: "NotificationServiceTest.shouldRetryFailedEmail",
    moduleId: "notifications",
    runner: "JUnit 5",
    triage: "regression",
    state: "escalated",
    reason: "Expected 3 delivery attempts but got 1",
    age: "13 min ago",
    at: "2025-01-21 14:43",
    build: 1852,
    requirement: { id: "US-105", title: "As a user, I want push notifications" },
    file: "backend/src/test/java/com/payflow/notifications/NotificationServiceTest.java",
    line: 31,
    owner: "J. Kim",
    note: "The retry policy stopped after the first attempt. The mail client's own retry was removed in Build 1852 and nothing replaced it, so a failed receipt email is now dropped silently. The test is correct and was left untouched - this is a real regression, routed to J. Kim.",
  },
  {
    id: "f6",
    test: "PaymentForm.test.tsx > shows a validation error for an expired card",
    moduleId: "payment-ui",
    runner: "Vitest",
    triage: "brittle",
    state: "awaiting-approval",
    reason: 'Unable to find text "Card expired"',
    age: "13 min ago",
    at: "2025-01-21 14:43",
    build: 1852,
    requirement: { id: "US-101", title: "As a user, I want to add a credit card" },
    file: "frontend/src/__tests__/PaymentForm.test.tsx",
    line: 31,
    repair: {
      proposedAt: "2025-01-21 14:48",
      language: "tsx",
      original: `await userEvent.type(screen.getByPlaceholderText("MM / YY"), "01 / 20");
await userEvent.click(screen.getByRole("button", { name: /pay/i }));

expect(screen.getByText("Card expired")).toBeInTheDocument();`,
      proposed: `await userEvent.type(screen.getByPlaceholderText("MM / YY"), "01 / 20");
await userEvent.click(screen.getByRole("button", { name: /pay/i }));

expect(await screen.findByRole("alert")).toHaveTextContent(/expired/i);
expect(onSubmit).not.toHaveBeenCalled();`,
      guard: {
        unchanged: { pass: true, detail: "Ran the repaired test against today's code · 1 test · 1 passed" },
        planted: {
          pass: true,
          detail: "Planted a bug that shows the alert and submits anyway · 1 test · 1 failed · caught",
        },
      },
      verdictLine: "Repair holds. It still catches the planted bug.",
      why: 'The error copy changed from "Card expired" to "This card has expired". The old test matched the exact sentence, so a wording change read as a broken feature. The repair matches the alert the form renders and checks that the payment was not submitted - the behaviour this test exists to protect.',
    },
  },
  {
    id: "f7",
    test: "AuthControllerTest.shouldRejectExpiredToken",
    moduleId: "auth",
    runner: "JUnit 5",
    triage: "healed",
    state: "healed",
    reason: "Was: expected 401 but got 403",
    age: "yesterday",
    at: "2025-01-20 16:34",
    build: 1851,
    requirement: { id: "US-101", title: "As a user, I want to add a credit card" },
    file: "backend/src/test/java/com/payflow/auth/AuthControllerTest.java",
    line: 33,
    note: "Expired tokens answer 401 now, not 403. S. Patel approved the repair on 20 Jan at 16:20 and the test has passed in every run since, including this one.",
  },
  {
    id: "f8",
    test: "PaymentForm.test.tsx > formats the amount with the account currency",
    moduleId: "payment-ui",
    runner: "Vitest",
    triage: "healed",
    state: "healed",
    reason: "Was: expected “$149.99”, found “€149.99”",
    age: "yesterday",
    at: "2025-01-20 16:34",
    build: 1851,
    requirement: { id: "US-106", title: "As a user, I want to view transaction history" },
    file: "frontend/src/__tests__/PaymentForm.test.tsx",
    line: 21,
    note: "The button label follows the account currency instead of always printing dollars. S. Patel approved the repair on 20 Jan at 16:21; it has passed in every run since.",
  },
];

/* ========================================================================== *
 * Generated test files - the real repository tree, filtered to tests
 * ========================================================================== */

export const testFiles: FileEntry[] = [
  { path: "frontend/src/__tests__/PaymentForm.test.tsx", type: "test", lines: 44, tags: ["healed"] },
  { path: "frontend/src/__tests__/TransactionList.test.tsx", type: "test", lines: 30 },
  { path: "frontend/src/hooks/__tests__/usePayment.test.ts", type: "test", lines: 21 },
  { path: "backend/src/test/java/com/payflow/payments/PaymentControllerTest.java", type: "test", lines: 48 },
  { path: "backend/src/test/java/com/payflow/payments/PaymentServiceTest.java", type: "test", lines: 58 },
  { path: "backend/src/test/java/com/payflow/kyc/KycServiceTest.java", type: "test", lines: 30 },
  { path: "backend/src/test/java/com/payflow/auth/AuthControllerTest.java", type: "test", lines: 35, tags: ["healed"] },
  { path: "backend/src/test/java/com/payflow/notifications/NotificationServiceTest.java", type: "test", lines: 33 },
];

/** Which requirement each test file protects, and its state in this run. */
export const testFileMeta: Record<string, TestFileMeta> = {
  "frontend/src/__tests__/PaymentForm.test.tsx": {
    requirement: "US-101",
    requirementTitle: "As a user, I want to add a credit card",
    failureId: "f6",
    healedId: "f8",
  },
  "frontend/src/__tests__/TransactionList.test.tsx": {
    requirement: "US-106",
    requirementTitle: "As a user, I want to view transaction history",
  },
  "frontend/src/hooks/__tests__/usePayment.test.ts": {
    requirement: "US-101",
    requirementTitle: "As a user, I want to add a credit card",
  },
  "backend/src/test/java/com/payflow/payments/PaymentControllerTest.java": {
    requirement: "US-101",
    requirementTitle: "As a user, I want to add a credit card",
    failureId: "f1",
  },
  "backend/src/test/java/com/payflow/payments/PaymentServiceTest.java": {
    requirement: "US-106",
    requirementTitle: "As a user, I want to view transaction history",
    failureId: "f2",
  },
  "backend/src/test/java/com/payflow/kyc/KycServiceTest.java": {
    requirement: "US-103",
    requirementTitle: "As a user, I want to verify my identity",
    failureId: "f4",
  },
  "backend/src/test/java/com/payflow/auth/AuthControllerTest.java": {
    requirement: "US-101",
    requirementTitle: "As a user, I want to add a credit card",
    healedId: "f7",
  },
  "backend/src/test/java/com/payflow/notifications/NotificationServiceTest.java": {
    requirement: "US-105",
    requirementTitle: "As a user, I want push notifications",
    failureId: "f5",
  },
};

export const testFileContents: Record<string, string> = {
  "frontend/src/__tests__/PaymentForm.test.tsx": `import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PaymentForm } from "../components/PaymentForm";

// Written from US-101 "As a user, I want to add a credit card"
describe("PaymentForm", () => {
  const onSubmit = vi.fn();

  it("renders the card fields", () => {
    render(<PaymentForm amount={149.99} currency="USD" onSubmit={onSubmit} />);

    expect(screen.getByPlaceholderText("Card number")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("MM / YY")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("CVC")).toBeInTheDocument();
  });

  it("formats the amount with the account currency", () => {
    render(<PaymentForm amount={149.99} currency="EUR" onSubmit={onSubmit} />);

    expect(screen.getByRole("button", { name: "Pay €149.99" })).toBeInTheDocument();
  });

  it("shows a validation error for an expired card", async () => {
    render(<PaymentForm amount={149.99} currency="USD" onSubmit={onSubmit} />);

    await userEvent.type(screen.getByPlaceholderText("Card number"), "4242424242424242");
    await userEvent.type(screen.getByPlaceholderText("MM / YY"), "01 / 20");
    await userEvent.click(screen.getByRole("button", { name: /pay/i }));

    expect(screen.getByText("Card expired")).toBeInTheDocument();
  });

  it("submits once the card is valid", async () => {
    render(<PaymentForm amount={149.99} currency="USD" onSubmit={onSubmit} />);

    await userEvent.type(screen.getByPlaceholderText("Card number"), "4242424242424242");
    await userEvent.type(screen.getByPlaceholderText("MM / YY"), "04 / 29");
    await userEvent.type(screen.getByPlaceholderText("CVC"), "123");
    await userEvent.click(screen.getByRole("button", { name: /pay/i }));

    expect(onSubmit).toHaveBeenCalledWith({ amount: 149.99, currency: "USD" });
  });
});`,
  "frontend/src/__tests__/TransactionList.test.tsx": `import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TransactionList } from "../components/TransactionList";

// Written from US-106 "As a user, I want to view transaction history"
const rows = [
  { id: "TXN-9001", amount: 149.99, currency: "USD", status: "SETTLED", createdAt: "2025-01-19T10:02:00Z" },
  { id: "TXN-9002", amount: 24.5, currency: "USD", status: "REFUNDED", createdAt: "2025-01-20T08:41:00Z" },
];

describe("TransactionList", () => {
  it("lists the newest transaction first", () => {
    render(<TransactionList transactions={rows} />);

    const ids = screen.getAllByTestId("txn-id").map((el) => el.textContent);
    expect(ids).toEqual(["TXN-9002", "TXN-9001"]);
  });

  it("labels a refund", () => {
    render(<TransactionList transactions={rows} />);

    expect(screen.getByText("Refunded")).toBeInTheDocument();
  });

  it("shows an empty state when there is nothing to list", () => {
    render(<TransactionList transactions={[]} />);

    expect(screen.getByText("No transactions yet")).toBeInTheDocument();
  });
});`,
  "frontend/src/hooks/__tests__/usePayment.test.ts": `import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePayment } from "../usePayment";
import * as api from "../../services/paymentApi";

// Written from US-101 "As a user, I want to add a credit card"
describe("usePayment", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("reports the error message when the gateway rejects the card", async () => {
    vi.spyOn(api, "createPayment").mockRejectedValue(new Error("Card declined"));
    const { result } = renderHook(() => usePayment());

    await act(async () => {
      await expect(result.current.processPayment({ amount: 10, currency: "USD" })).rejects.toThrow();
    });

    expect(result.current.error).toBe("Card declined");
    expect(result.current.loading).toBe(false);
  });
});`,
  "backend/src/test/java/com/payflow/payments/PaymentControllerTest.java": `package com.payflow.payments;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

// Written from US-101 "As a user, I want to add a credit card"
@SpringBootTest
@AutoConfigureMockMvc
class PaymentControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private PaymentFixtures fixtures;

    @Test
    void shouldCreatePayment() throws Exception {
        mockMvc.perform(post("/api/v1/payments")
                .contentType("application/json")
                .content("""
                    { "amount": 14999, "currency": "USD", "source": "tok_visa" }
                    """))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.status").value("CAPTURED"));
    }

    @Test
    void shouldReturn404ForUnknownPayment() throws Exception {
        mockMvc.perform(post("/api/v1/payments/{id}/refund", "PAY-does-not-exist"))
            .andExpect(status().isNotFound());
    }

    @Test
    void shouldRefundPayment() throws Exception {
        Payment payment = fixtures.seedCapturedPayment();

        mockMvc.perform(post("/api/v1/payments/{id}/refund", payment.getId()))
            .andExpect(status().isOk());
    }
}`,
  "backend/src/test/java/com/payflow/payments/PaymentServiceTest.java": `package com.payflow.payments;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.payflow.kyc.KycRequiredException;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.transaction.annotation.Transactional;

// Written from US-106 "As a user, I want to view transaction history"
// and US-103 "As a user, I want to verify my identity"
@SpringBootTest
@Transactional
class PaymentServiceTest {

    @Autowired
    private PaymentService paymentService;

    @Test
    void shouldCapturePayment() {
        Payment payment = paymentService.capture(request(14_999L, "USD"));

        assertEquals(PaymentStatus.CAPTURED, payment.getStatus());
        assertEquals(14_999L, payment.getAmountMinor());
    }

    @Test
    void shouldSplitSettlementFees() {
        Payment payment = paymentService.capture(request(12_000L, "USD"));

        FeeBreakdown fees = payment.getFeeBreakdown();
        assertEquals(348L, fees.platformFee());
    }

    @Test
    void shouldRecordRefundAgainstOriginalPayment() {
        Payment payment = paymentService.capture(request(4_000L, "USD"));

        Refund refund = paymentService.refund(payment.getId());

        assertEquals(payment.getId(), refund.paymentId());
        assertEquals(4_000L, refund.amountMinor());
    }

    @Test
    void shouldRejectPaymentAboveKycLimit() {
        Customer unverified = customers.unverified();

        assertThrows(KycRequiredException.class,
            () -> paymentService.capture(request(140_000L, "USD", unverified)));
    }

    private PaymentRequest request(long amountMinor, String currency) {
        return new PaymentRequest(amountMinor, currency, "tok_visa", customers.verified());
    }
}`,
  "backend/src/test/java/com/payflow/kyc/KycServiceTest.java": `package com.payflow.kyc;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

// Written from US-103 "As a user, I want to verify my identity"
@ExtendWith(MockitoExtension.class)
class KycServiceTest {

    @Mock
    private DocumentVerifier documentVerifier;

    @InjectMocks
    private KycService kycService;

    private final Document document = Document.passport("P-4521", "2031-04-01");

    @Test
    void shouldVerifyDocument() {
        kycService.verify(document);

        verify(documentVerifier).verify(document);
    }
}`,
  "backend/src/test/java/com/payflow/auth/AuthControllerTest.java": `package com.payflow.auth;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

// Written from US-101 "As a user, I want to add a credit card"
@SpringBootTest
@AutoConfigureMockMvc
class AuthControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private TokenFixtures tokens;

    @Test
    void shouldAllowValidToken() throws Exception {
        mockMvc.perform(get("/api/v1/me").header("Authorization", tokens.valid()))
            .andExpect(status().isOk());
    }

    // Repaired 20 Jan, approved by S. Patel: expired tokens answer 401, not 403.
    @Test
    void shouldRejectExpiredToken() throws Exception {
        mockMvc.perform(get("/api/v1/me").header("Authorization", tokens.expired()))
            .andExpect(status().isUnauthorized());
    }
}`,
  "backend/src/test/java/com/payflow/notifications/NotificationServiceTest.java": `package com.payflow.notifications;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

// Written from US-105 "As a user, I want push notifications"
@ExtendWith(MockitoExtension.class)
class NotificationServiceTest {

    @Mock
    private MailClient mailClient;

    @InjectMocks
    private NotificationService notificationService;

    @Test
    void shouldRetryFailedEmail() {
        when(mailClient.send(any())).thenThrow(new MailException("smtp timeout"));

        notificationService.sendReceipt("USR-4521", "TXN-9001");

        verify(mailClient, times(3)).send(any());
    }
}`,
};
