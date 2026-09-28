// Generated from the api-contract by the platform. Do not edit by hand.

export interface Consignment {
  id: string;
  batchNumber: string;
  status: string;
  pharmacyId: string;
}

export interface Container {
  id: string;
  sensorId: string;
  permittedRangeMin: number;
  permittedRangeMax: number;
}

export interface Vehicle {
  id: string;
  registration: string;
}

export interface Route {
  id: string;
  stops: string;
}

export interface Signature {
  id: string;
  consignmentId: string;
  pharmacistId: string;
}

export interface PatchVehiclesIdRequest {
  registration: string;
}

export interface PostConsignmentsRequest {
  batchNumber: string;
  status: string;
  pharmacyId: string;
}

export interface PostContainersRequest {
  sensorId: string;
  permittedRangeMin: number;
  permittedRangeMax: number;
}
