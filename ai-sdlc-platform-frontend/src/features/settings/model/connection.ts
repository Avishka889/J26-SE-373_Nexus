import type { Connection, ConnectionProbe } from "@/entities/settings";

export type ConnectionTone = "success" | "warning" | "error" | "default";

export interface ConnectionStatus {
  label: string;
  tone: ConnectionTone;
}

/** The check's verdicts, in the words a reader uses. */
const VERDICT_WORDS: Record<ConnectionProbe["verdict"], string> = {
  SUITABLE: "Works",
  WORKABLE: "Works with limits",
  UNUSABLE: "Does not work",
};

/**
 * What a stored credential is known to do, from its last check.
 *
 * "Connected" stayed green whatever the check said, because it meant only that
 * a credential was stored: a token the check found unusable read as connected.
 */
export function connectionStatus(connection: Connection | undefined): ConnectionStatus {
  if (!connection) return { label: "Not connected", tone: "default" };
  switch (connection.probe?.verdict) {
    case "SUITABLE":
      return { label: "Connected", tone: "success" };
    case "WORKABLE":
      return { label: "Works with limits", tone: "warning" };
    case "UNUSABLE":
      return { label: "Not working", tone: "error" };
    default:
      return { label: "Saved, not checked", tone: "default" };
  }
}

/** The check's verdict and its reason, as a sentence. */
export function verdictSentence(probe: ConnectionProbe): string {
  return `${VERDICT_WORDS[probe.verdict]}: ${probe.reason}`;
}

/** The toast a verdict deserves: a token that works with limits is a warning, not a success. */
export function verdictTone(verdict: ConnectionProbe["verdict"] | undefined): "success" | "warning" | "error" {
  if (verdict === "UNUSABLE") return "error";
  if (verdict === "WORKABLE") return "warning";
  return "success";
}

/** A verdict's title for a toast, in words. */
export function verdictTitle(verdict: ConnectionProbe["verdict"] | undefined): string {
  return verdict ? VERDICT_WORDS[verdict] : "Not checked";
}
