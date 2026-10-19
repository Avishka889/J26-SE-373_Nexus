// Generated from the api-contract by the platform. Do not edit by hand.

export interface Product {
  id: string;
  storefrontId: string;
  name: string;
  price: number;
  category: string;
}

export interface Cart {
  id: string;
  storefrontId: string;
  lineItems: string;
  updatedAt: string;
}

export interface Order {
  id: string;
  storefrontId: string;
  status: string;
  total: number;
  placedAt: string;
}

export interface StockLevel {
  id: string;
  productId: string;
  available: number;
  syncedAt: string;
}

export interface PatchOrdersIdRequest {
  storefrontId: string;
  status: string;
  total: number;
  placedAt: string;
}

export interface PostOrdersRequest {
  storefrontId: string;
  status: string;
  total: number;
  placedAt: string;
}
