// Generated from the api-contract by the platform. Do not edit by hand.
// The agreement checker reads the `implements` headers below; the
// generated frontend may call these methods and nothing else.

import type { Consignment, Container, PatchVehiclesIdRequest, PostConsignmentsRequest, PostContainersRequest, Route, Signature, Vehicle } from "./types";

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

  // implements get-consignments GET /consignments
  getConsignments(): Promise<Consignment[]> {
    return this.request<Consignment[]>("GET", `${this.baseUrl}/consignments`);
  }

  // implements get-consignments-id GET /consignments/{id}
  getConsignmentsId(id: string): Promise<Consignment> {
    return this.request<Consignment>("GET", `${this.baseUrl}/consignments/${id}`);
  }

  // implements get-containers-id GET /containers/{id}
  getContainersId(id: string): Promise<Container> {
    return this.request<Container>("GET", `${this.baseUrl}/containers/${id}`);
  }

  // implements get-routes GET /routes
  getRoutes(): Promise<Route[]> {
    return this.request<Route[]>("GET", `${this.baseUrl}/routes`);
  }

  // implements get-routes-id GET /routes/{id}
  getRoutesId(id: string): Promise<Route> {
    return this.request<Route>("GET", `${this.baseUrl}/routes/${id}`);
  }

  // implements get-signatures-id GET /signatures/{id}
  getSignaturesId(id: string): Promise<Signature> {
    return this.request<Signature>("GET", `${this.baseUrl}/signatures/${id}`);
  }

  // implements get-vehicles-id GET /vehicles/{id}
  getVehiclesId(id: string): Promise<Vehicle> {
    return this.request<Vehicle>("GET", `${this.baseUrl}/vehicles/${id}`);
  }

  // implements patch-vehicles-id PATCH /vehicles/{id}
  patchVehiclesId(id: string, body: PatchVehiclesIdRequest): Promise<Vehicle> {
    return this.request<Vehicle>("PATCH", `${this.baseUrl}/vehicles/${id}`, body);
  }

  // implements post-consignments POST /consignments
  postConsignments(body: PostConsignmentsRequest): Promise<Consignment> {
    return this.request<Consignment>("POST", `${this.baseUrl}/consignments`, body);
  }

  // implements post-consignments-id-collect POST /consignments/{id}/collect
  postConsignmentsIdCollect(id: string): Promise<Consignment> {
    return this.request<Consignment>("POST", `${this.baseUrl}/consignments/${id}/collect`);
  }

  // implements post-containers POST /containers
  postContainers(body: PostContainersRequest): Promise<Container> {
    return this.request<Container>("POST", `${this.baseUrl}/containers`, body);
  }

  // implements post-routes-id-follow POST /routes/{id}/follow
  postRoutesIdFollow(id: string): Promise<Route> {
    return this.request<Route>("POST", `${this.baseUrl}/routes/${id}/follow`);
  }

  // implements post-routes-id-reassign-stop-on POST /routes/{id}/reassign-stop-on
  postRoutesIdReassignStopOn(id: string): Promise<Route> {
    return this.request<Route>("POST", `${this.baseUrl}/routes/${id}/reassign-stop-on`);
  }

  // implements post-signatures-id-capture POST /signatures/{id}/capture
  postSignaturesIdCapture(id: string): Promise<Signature> {
    return this.request<Signature>("POST", `${this.baseUrl}/signatures/${id}/capture`);
  }

  // implements post-signatures-id-provide POST /signatures/{id}/provide
  postSignaturesIdProvide(id: string): Promise<Signature> {
    return this.request<Signature>("POST", `${this.baseUrl}/signatures/${id}/provide`);
  }
}
