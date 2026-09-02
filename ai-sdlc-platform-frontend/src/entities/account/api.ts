import { isLive } from "@/lib/env";
import { HttpError, http } from "@/lib/http";

export interface AccountUser {
  id: string;
  email: string;
  name: string;
}

/**
 * Where this tab's sign-in stands.
 *
 * - `checking`: the server is being asked who is signed in;
 * - `signed-in`, with the account;
 * - `signed-out`: nobody is, or the session ended;
 * - `unsupported`: the server answering predates sign-in, so it has no
 *   `/auth` routes, and the app behaves as it did before them: the form opens
 *   the workspace for this tab. It ends when that server is migrated and
 *   restarted, and nothing here needs to change when it does.
 */
export type Session =
  | { status: "checking" }
  | { status: "signed-in"; user: AccountUser }
  | { status: "signed-out" }
  | { status: "unsupported"; signedIn: boolean };

let session: Session = { status: "checking" };
const listeners = new Set<() => void>();

function set(next: Session) {
  session = next;
  for (const listener of listeners) listener();
}

export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getSession(): Session {
  return session;
}

export function isSignedIn(current: Session): boolean {
  return current.status === "signed-in" || (current.status === "unsupported" && current.signedIn);
}

/**
 * A local "signed in" flag, for the fixture modes and a server without sign-in.
 *
 * Neither has accounts, so there is nothing to prove; the flag only remembers
 * that this browser opened the workspace, as the old form did. Never used when
 * the server signs people in.
 */
const LOCAL_KEY = "sdlc-signed-in-locally";

function signedInLocally(): boolean {
  try {
    if (localStorage.getItem(LOCAL_KEY) === "1") return true;
    // The flag the form set before sign-in existed, so a browser that had
    // opened the workspace is not sent back to the form by this change alone.
    const legacy = JSON.parse(localStorage.getItem("nexus-session") ?? "null") as {
      state?: { isAuthenticated?: unknown };
    } | null;
    return legacy?.state?.isAuthenticated === true;
  } catch {
    return false;
  }
}

function rememberLocally(signedIn: boolean) {
  try {
    if (signedIn) localStorage.setItem(LOCAL_KEY, "1");
    else localStorage.removeItem(LOCAL_KEY);
  } catch {
    // Remembered for this page only.
  }
}

/** The account the fixture modes sign in as. */
const DEMO_USER: AccountUser = { id: "u_demo", email: "alex@acme.dev", name: "Alex Chen" };

/** Ask the server who is signed in, once at startup. */
export async function checkSession(): Promise<void> {
  if (!isLive("projects")) {
    set(signedInLocally() ? { status: "signed-in", user: DEMO_USER } : { status: "signed-out" });
    return;
  }
  try {
    const { user } = await http.get<{ user: AccountUser }>("/auth/me", { needsSession: false });
    set({ status: "signed-in", user });
  } catch (error) {
    if (error instanceof HttpError && error.status === 404) {
      set({ status: "unsupported", signedIn: signedInLocally() });
    } else {
      set({ status: "signed-out" });
    }
  }
}

export async function signIn(email: string, password: string): Promise<void> {
  if (!isLive("projects")) {
    rememberLocally(true);
    set({ status: "signed-in", user: { ...DEMO_USER, email: email.trim() || DEMO_USER.email } });
    return;
  }
  if (session.status === "unsupported") {
    rememberLocally(true);
    set({ status: "unsupported", signedIn: true });
    return;
  }
  const { user } = await http.post<{ user: AccountUser }>(
    "/auth/login",
    { email, password },
    { needsSession: false },
  );
  set({ status: "signed-in", user });
}

/** Create an account and sign it in; `adopted` when it took over the projects from before sign-in. */
export async function register(
  name: string,
  email: string,
  password: string,
): Promise<{ adopted: boolean }> {
  if (!isLive("projects")) {
    rememberLocally(true);
    set({ status: "signed-in", user: { id: DEMO_USER.id, name: name.trim(), email: email.trim() } });
    return { adopted: false };
  }
  if (session.status === "unsupported") {
    throw new Error(
      "This server does not have sign-in yet, so there is no account to create. Log in with any email and password.",
    );
  }
  const answer = await http.post<{ user: AccountUser; adopted: boolean }>(
    "/auth/register",
    { name, email, password },
    { needsSession: false },
  );
  set({ status: "signed-in", user: answer.user });
  return { adopted: answer.adopted };
}

export async function signOut(): Promise<void> {
  rememberLocally(false);
  if (!isLive("projects") || session.status === "unsupported") {
    set(session.status === "unsupported" ? { status: "unsupported", signedIn: false } : { status: "signed-out" });
    return;
  }
  try {
    await http.post("/auth/logout", undefined, { needsSession: false });
  } finally {
    set({ status: "signed-out" });
  }
}

/** The server ended the session: a request needing one answered 401. */
export function sessionEnded(): void {
  if (session.status === "signed-in") set({ status: "signed-out" });
}

/** The account's name changed (Settings), so the session says the new one. */
export function renamed(name: string): void {
  if (session.status === "signed-in") set({ status: "signed-in", user: { ...session.user, name } });
}
