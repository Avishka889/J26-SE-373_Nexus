// Generated from the api-contract by the platform. Do not edit by hand.

export interface Task {
  id: string;
  name: string;
}

export interface TaskList {
  id: string;
  taskIds: string;
}

export interface PostTasksRequest {
  name: string;
}
