import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpError, messageOf } from "./http";

afterEach(() => {
  vi.unstubAllGlobals();
});

function answer(status: number, body: string, type = "application/json") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body, { status, headers: { "Content-Type": type } })),
  );
}

async function failureOf(call: Promise<unknown>): Promise<unknown> {
  try {
    await call;
  } catch (error) {
    return error;
  }
  throw new Error("the request was expected to fail");
}

function captureFetch() {
  const calls: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) => {
      calls.push(init);
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

describe("http", () => {
  it("sends a FormData body untouched, with no content type of its own", async () => {
    // The browser has to write the multipart boundary itself. Setting the header
    // here produces one without a boundary, and the server rejects the body.
    const calls = captureFetch();
    const form = new FormData();
    form.append("file", new File(["hello"], "brief.md", { type: "text/markdown" }));

    await http.post("/documents/extract", form);

    expect(calls[0].body).toBe(form);
    expect((calls[0].headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("still serialises an ordinary object as JSON", async () => {
    const calls = captureFetch();
    await http.post("/projects", { name: "Calculator" });

    expect(calls[0].body).toBe('{"name":"Calculator"}');
    expect((calls[0].headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
});

/**
 * A failure reads as a sentence a person can act on.
 *
 * The orchestrator answers every refusal with `{"error": sentence}`, and the
 * message used to be "HTTP 409 POST /projects/p_1/testing/decision" while the
 * sentence sat unread in `body`. Every toast that showed `error.message`, in
 * Design, Code, Testing and Settings, showed the transport line instead.
 */
describe("a failed request", () => {
  it("reads in the server's words when the server gave a reason", async () => {
    answer(409, JSON.stringify({ error: "there is no testing decision waiting on this project" }));

    const error = await failureOf(http.post("/projects/p_1/testing/decision", { kind: "approved" }));

    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).message).toBe("There is no testing decision waiting on this project");
    expect((error as HttpError).status).toBe(409);
    expect((error as HttpError).body).toEqual({
      error: "there is no testing decision waiting on this project",
    });
  });

  it("says what kind of failure it was when the body has no reason", async () => {
    answer(502, "<html>Bad gateway</html>", "text/html");
    expect(messageOf(await failureOf(http.get("/projects")))).toBe(
      "The server hit an error and could not finish. Try again in a moment.",
    );

    answer(404, "");
    expect(messageOf(await failureOf(http.get("/projects/p_gone")))).toBe(
      "That could not be found. It may have been deleted.",
    );
  });

  it("says the server cannot be reached, not 'Failed to fetch'", async () => {
    const offline = new TypeError("Failed to fetch");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(offline)));

    const error = await failureOf(http.get("/projects"));

    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).status).toBe(0);
    expect((error as HttpError).message).toBe(
      "Cannot reach the server. Check that it is running, then try again.",
    );
    expect((error as HttpError).cause).toBe(offline);
  });

  it("says the server took too long when the timeout ends it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("The operation was aborted.", "AbortError")),
            );
          }),
      ),
    );

    const error = await failureOf(http.get("/projects", { timeoutMs: 5 }));

    expect((error as HttpError).status).toBe(408);
    expect((error as HttpError).message).toBe("The server took too long to answer. Try again.");
  });

  it("passes a caller's own cancel through instead of reporting a failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("The operation was aborted.", "AbortError")),
            );
          }),
      ),
    );
    const cancel = new AbortController();

    const pending = failureOf(http.get("/projects", { signal: cancel.signal }));
    cancel.abort();
    const error = await pending;

    expect(error).not.toBeInstanceOf(HttpError);
    expect((error as DOMException).name).toBe("AbortError");
  });
});

describe("messageOf", () => {
  it("reads any thrown value as a sentence", () => {
    expect(messageOf(new Error("Pick a target first"))).toBe("Pick a target first");
    expect(messageOf("nope")).toBe("Something went wrong. Try again.");
    expect(messageOf(undefined, "The file could not be read.")).toBe("The file could not be read.");
  });
});
