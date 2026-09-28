// Generated from the api-contract by the platform. Do not edit by hand.
// The agreement checker reads the `implements` headers below; the
// generated frontend may call these methods and nothing else.

import type { PostTasksRequest, Task, TaskList } from "./types";

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

  // implements delete-tasks-id DELETE /tasks/{id}
  deleteTasksId(id: string): Promise<void> {
    return this.request<void>("DELETE", `${this.baseUrl}/tasks/${id}`);
  }

  // implements get-task-lists-id GET /task-lists/{id}
  getTaskListsId(id: string): Promise<TaskList> {
    return this.request<TaskList>("GET", `${this.baseUrl}/task-lists/${id}`);
  }

  // implements get-tasks GET /tasks
  getTasks(): Promise<Task[]> {
    return this.request<Task[]>("GET", `${this.baseUrl}/tasks`);
  }

  // implements get-tasks-id GET /tasks/{id}
  getTasksId(id: string): Promise<Task> {
    return this.request<Task>("GET", `${this.baseUrl}/tasks/${id}`);
  }

  // implements post-tasks POST /tasks
  postTasks(body: PostTasksRequest): Promise<Task> {
    return this.request<Task>("POST", `${this.baseUrl}/tasks`, body);
  }
}
