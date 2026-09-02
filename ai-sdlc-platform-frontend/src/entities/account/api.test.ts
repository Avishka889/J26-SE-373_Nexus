import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

/** The account store and the http client as the running app loads them. */
async function live() {
  vi.resetModules();
  vi.stubEnv("MODE", "development");
  const http = await import("@/lib/http");
  const account = await import("./api");
  return { http, account };
}

function answering(status: number, body: unknown) {
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) =>
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const ADA = { id: "u_1", email: "ada@example.com", name: "Ada" };

/**
 * The session is the server's to say.
 *
 * The form used to set a flag in the browser, so any address and any password
 * opened every project. Now the server says who is signed in, by a cookie the
 * page cannot read.
 */
describe("the session", () => {
  it("is signed in when the server knows the cookie", async () => {
    const fetch = answering(200, { user: ADA });
    const { account } = await live();

    await account.checkSession();

    expect(account.getSession()).toEqual({ status: "signed-in", user: ADA });
    expect(fetch.mock.calls[0][1]?.credentials).toBe("include");
  });

  it("is signed out on a 401, without treating it as a session that ended", async () => {
    answering(401, { error: "Sign in to continue." });
    const { account, http } = await live();
    const ended = vi.fn();
    http.setUnauthorizedHandler(ended);

    await account.checkSession();

    expect(account.getSession()).toEqual({ status: "signed-out" });
    expect(ended).not.toHaveBeenCalled();
  });

  it("falls back to the old local sign-in when the server predates sign-in", async () => {
    answering(404, { detail: "Not Found" });
    const { account } = await live();

    await account.checkSession();
    await account.signIn("anyone@example.com", "anything");

    expect(account.getSession()).toEqual({ status: "unsupported", signedIn: true });
  });

  it("refuses a wrong password in the server's words, and stays signed out", async () => {
    answering(401, { error: "That email and password do not match an account." });
    const { account } = await live();

    await expect(account.signIn("ada@example.com", "wrong")).rejects.toThrow(
      "That email and password do not match an account.",
    );
    expect(account.getSession().status).not.toBe("signed-in");
  });

  it("signs in, and is signed out again when the server ends the session", async () => {
    answering(200, { user: ADA });
    const { account } = await live();
    await account.signIn("ada@example.com", "correct horse battery staple");
    expect(account.getSession()).toEqual({ status: "signed-in", user: ADA });

    account.sessionEnded();

    expect(account.getSession()).toEqual({ status: "signed-out" });
  });

  it("signs out on the server", async () => {
    const fetch = answering(200, { user: ADA });
    const { account } = await live();
    await account.signIn("ada@example.com", "correct horse battery staple");
    answering(204, undefined);

    await account.signOut();

    expect(account.getSession()).toEqual({ status: "signed-out" });
    expect(fetch).toHaveBeenCalled();
  });
});
