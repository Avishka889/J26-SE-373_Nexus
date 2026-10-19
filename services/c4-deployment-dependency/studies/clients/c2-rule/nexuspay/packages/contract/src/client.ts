// Generated from the api-contract by the platform. Do not edit by hand.
// The agreement checker reads the `implements` headers below; the
// generated frontend may call these methods and nothing else.

import type { AuditEntry, Customer, PatchVerificationsIdRequest, Payment, PostVerificationsRequest, Verification } from "./types";

export class ApiClient {
  constructor(private readonly baseUrl: string) {}

  private async request<T>(method: string, url: string, body?: unknown): Promise<T> {
    const response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(`${method} ${url} answered ${response.status}`);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  // implements get-audit-entries GET /audit-entries
  getAuditEntries(): Promise<AuditEntry[]> {
    return this.request<AuditEntry[]>("GET", `${this.baseUrl}/audit-entries`);
  }

  // implements get-payments GET /payments
  getPayments(): Promise<Payment[]> {
    return this.request<Payment[]>("GET", `${this.baseUrl}/payments`);
  }

  // implements get-payments-id GET /payments/{id}
  getPaymentsId(id: string): Promise<Payment> {
    return this.request<Payment>("GET", `${this.baseUrl}/payments/${id}`);
  }

  // implements get-verifications GET /verifications
  getVerifications(): Promise<Verification[]> {
    return this.request<Verification[]>("GET", `${this.baseUrl}/verifications`);
  }

  // implements get-verifications-id GET /verifications/{id}
  getVerificationsId(id: string): Promise<Verification> {
    return this.request<Verification>("GET", `${this.baseUrl}/verifications/${id}`);
  }

  // implements patch-verifications-id PATCH /verifications/{id}
  patchVerificationsId(id: string, body: PatchVerificationsIdRequest): Promise<Verification> {
    return this.request<Verification>("PATCH", `${this.baseUrl}/verifications/${id}`, body);
  }

  // implements post-payments-id-make POST /payments/{id}/make
  postPaymentsIdMake(id: string): Promise<Payment> {
    return this.request<Payment>("POST", `${this.baseUrl}/payments/${id}/make`);
  }

  // implements post-payments-id-settle POST /payments/{id}/settle
  postPaymentsIdSettle(id: string): Promise<Payment> {
    return this.request<Payment>("POST", `${this.baseUrl}/payments/${id}/settle`);
  }

  // implements post-verifications POST /verifications
  postVerifications(body: PostVerificationsRequest): Promise<Verification> {
    return this.request<Verification>("POST", `${this.baseUrl}/verifications`, body);
  }
}
