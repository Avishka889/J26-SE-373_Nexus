// Generated from the api-contract by the platform. Do not edit by hand.
// The agreement checker reads the `implements` headers below; the
// generated frontend may call these methods and nothing else.

import type { Cart, Order, PatchOrdersIdRequest, PostOrdersRequest, Product, StockLevel } from "./types";

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

  // implements get-carts-id GET /carts/{id}
  getCartsId(id: string): Promise<Cart> {
    return this.request<Cart>("GET", `${this.baseUrl}/carts/${id}`);
  }

  // implements get-orders-id GET /orders/{id}
  getOrdersId(id: string): Promise<Order> {
    return this.request<Order>("GET", `${this.baseUrl}/orders/${id}`);
  }

  // implements get-products GET /products
  getProducts(): Promise<Product[]> {
    return this.request<Product[]>("GET", `${this.baseUrl}/products`);
  }

  // implements get-products-id GET /products/{id}
  getProductsId(id: string): Promise<Product> {
    return this.request<Product>("GET", `${this.baseUrl}/products/${id}`);
  }

  // implements patch-orders-id PATCH /orders/{id}
  patchOrdersId(id: string, body: PatchOrdersIdRequest): Promise<Order> {
    return this.request<Order>("PATCH", `${this.baseUrl}/orders/${id}`, body);
  }

  // implements post-carts-id-fill POST /carts/{id}/fill
  postCartsIdFill(id: string): Promise<Cart> {
    return this.request<Cart>("POST", `${this.baseUrl}/carts/${id}/fill`);
  }

  // implements post-orders POST /orders
  postOrders(body: PostOrdersRequest): Promise<Order> {
    return this.request<Order>("POST", `${this.baseUrl}/orders`, body);
  }

  // implements post-orders-id-settle POST /orders/{id}/settle
  postOrdersIdSettle(id: string): Promise<Order> {
    return this.request<Order>("POST", `${this.baseUrl}/orders/${id}/settle`);
  }

  // implements post-stock-levels-id-report POST /stock-levels/{id}/report
  postStockLevelsIdReport(id: string): Promise<StockLevel> {
    return this.request<StockLevel>("POST", `${this.baseUrl}/stock-levels/${id}/report`);
  }
}
