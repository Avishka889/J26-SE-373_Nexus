// Generated from the api-contract by the platform. Do not edit by hand.
// The agreement checker reads the `implements` headers below; the
// generated frontend may call these methods and nothing else.

import type { Calculation, PostCalculationsRequest } from "./types";

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

  // implements get-calculations GET /calculations
  getCalculations(): Promise<Calculation[]> {
    return this.request<Calculation[]>("GET", `${this.baseUrl}/calculations`);
  }

  // implements get-calculations-id GET /calculations/{id}
  getCalculationsId(id: string): Promise<Calculation> {
    return this.request<Calculation>("GET", `${this.baseUrl}/calculations/${id}`);
  }

  // implements post-calculations POST /calculations
  postCalculations(body: PostCalculationsRequest): Promise<Calculation> {
    return this.request<Calculation>("POST", `${this.baseUrl}/calculations`, body);
  }
}
