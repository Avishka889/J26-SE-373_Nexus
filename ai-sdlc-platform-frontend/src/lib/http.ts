/**
 * Sole fetch entry point: base URL, auth headers, timeouts, typed errors.
 * Feature api/ modules must call this, never raw fetch.
 */

import { env } from "@/lib/env";

/**
 * A request that failed, with a message a person can act on.
 *
 * `status` is 0 when the server could not be reached at all. `body` is the
 * parsed answer, for callers that need the structured `detail` beside it.
 */
export class HttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body?: unknown,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "HttpError";
  }
}

const UNREACHABLE = "Cannot reach the server. Check that it is running, then try again.";
const TOO_SLOW = "The server took too long to answer. Try again.";

const BY_STATUS: Record<number, string> = {
  400: "The server refused this request.",
  401: "Your session has ended. Sign in again.",
  403: "You do not have access to this.",
  404: "That could not be found. It may have been deleted.",
  408: TOO_SLOW,
  409: "That conflicts with what the server has now. Refresh and try again.",
  413: "That is too large for the server to accept.",
  422: "The server could not read this request.",
  429: "Too many requests at once. Wait a moment and try again.",
};

/**
 * What a failed answer says, in the server's words when it gave any.
 *
 * The orchestrator answers every refusal with `{"error": sentence}` (its
 * `errors.py`), and the sentence is the useful part: which guard, which
 * version, what to do next. The message used to be "HTTP 409 POST /path" while
 * the sentence sat unread in `body`, so every toast showing `error.message`
 * showed the transport line. An answer with no sentence, a proxy's HTML page or
 * an empty body, gets one that says what kind of failure it was.
 */
function messageFor(status: number, body: unknown): string {
  const sentence = (body as { error?: unknown } | undefined)?.error;
  if (typeof sentence === "string" && sentence.trim()) {
    const text = sentence.trim();
    return text.charAt(0).toUpperCase() + text.slice(1);
  }
  if (BY_STATUS[status]) return BY_STATUS[status];
  if (status >= 500) return "The server hit an error and could not finish. Try again in a moment.";
  return `The request failed (status ${status}).`;
}

/** Any thrown value as a sentence: an `HttpError`'s is already the server's. */
export function messageOf(error: unknown, fallback = "Something went wrong. Try again."): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

async function bodyOf(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  timeoutMs?: number;
  /**
   * Whether a 401 here means the session ended. True for everything but the
   * sign-in calls themselves, where a 401 is the answer (a wrong password, or
   * nobody signed in yet) and must not send the page to the sign-in screen.
   */
  needsSession?: boolean;
  /** A file rather than JSON: the answer comes back as a Blob, as sent. */
  as?: "json" | "blob";
}

let authToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

/** Set by auth flow when a real token exists. Never persist in Zustand. */
export function setHttpAuthToken(token: string | null) {
  authToken = token;
}

export function getHttpAuthToken(): string | null {
  return authToken;
}

/** Wire from app/providers: clear the session and redirect on a 401. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

async function request<T>(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<T> {
  const url = path.startsWith("http")
    ? path
    : `${env.apiUrl.replace(/\/$/, "")}${path.startsWith("/") ? path : `/${path}`}`;

  const headers: Record<string, string> = {
    Accept: options.as === "blob" ? "*/*" : "application/json",
    ...options.headers,
  };

  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  // FormData has to go through untouched: the browser writes the multipart
  // boundary into the content type itself, and setting the header here produces
  // one without a boundary that the server cannot parse.
  const isForm = options.body instanceof FormData;
  if (options.body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
  }

  const timeoutMs = options.timeoutMs ?? 30_000;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  options.signal?.addEventListener("abort", onAbort);

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      // The session is an HttpOnly cookie the page cannot read, and the
      // orchestrator is another origin (another port), so the browser sends it
      // only when asked to.
      credentials: "include",
      body:
        options.body === undefined
          ? undefined
          : isForm
            ? (options.body as FormData)
            : JSON.stringify(options.body),
      signal: controller.signal,
    });
  } catch (err) {
    // The caller's own cancel (a query being dropped) is not a failure to
    // report: it goes back as it came, which is what the query cache expects.
    if (options.signal?.aborted) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new HttpError(TOO_SLOW, 408, undefined, { cause: err });
    }
    // fetch rejects only when no answer came at all: the server is down, the
    // address is wrong, or the connection dropped. "Failed to fetch" says none
    // of that to a person.
    throw new HttpError(UNREACHABLE, 0, undefined, { cause: err });
  } finally {
    window.clearTimeout(timeoutId);
    options.signal?.removeEventListener("abort", onAbort);
  }

  if (response.status === 401) {
    const body = await bodyOf(response);
    if (options.needsSession !== false) {
      setHttpAuthToken(null);
      onUnauthorized?.();
    }
    throw new HttpError(messageFor(401, body), 401, body);
  }

  if (!response.ok) {
    const body = await bodyOf(response);
    throw new HttpError(messageFor(response.status, body), response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  if (options.as === "blob") return (await response.blob()) as T;
  return (await response.json()) as T;
}

export const http = {
  get: <T>(path: string, options?: Omit<RequestOptions, "body">) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">) =>
    request<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">) =>
    request<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">) =>
    request<T>("PATCH", path, { ...options, body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, "body">) => request<T>("DELETE", path, options),
};
