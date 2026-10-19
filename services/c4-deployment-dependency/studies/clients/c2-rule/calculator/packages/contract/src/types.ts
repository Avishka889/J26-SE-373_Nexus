// Generated from the api-contract by the platform. Do not edit by hand.

export interface Calculation {
  id: string;
  expression: string;
  result: number;
  computedAt: string;
}

export interface PostCalculationsRequest {
  expression: string;
  result: number;
  computedAt: string;
}
