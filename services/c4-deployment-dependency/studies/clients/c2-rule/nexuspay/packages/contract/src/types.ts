// Generated from the api-contract by the platform. Do not edit by hand.

export interface Customer {
  id: string;
  email: string;
  displayName: string;
  verifiedAt: string;
}

export interface Payment {
  id: string;
  amount: number;
  method: string;
  status: string;
  createdAt: string;
}

export interface Verification {
  id: string;
  documentType: string;
  status: string;
  reviewedBy: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  actor: string;
  at: string;
}

export interface PatchVerificationsIdRequest {
  documentType: string;
  status: string;
  reviewedBy: string;
}

export interface PostVerificationsRequest {
  documentType: string;
  status: string;
  reviewedBy: string;
}
