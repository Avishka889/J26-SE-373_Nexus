/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Claimsrefused = number;
export type Claimsverified = number;
export type Generatedat = string;
export type Modelid = string;
export type Id = string;
export type Kind = "breaking" | "removal" | "behavioural" | "deprecation" | "security" | "fix" | "feature" | "other";
export type Quote = string;
export type Sourceurl = string;
export type Symbols = string[];
export type Version = string;
export type Claims = ChangelogClaim[];
export type Completiontokens = number;
export type Durationseconds = number;
export type Error = string;
export type Modelid1 = string;
export type Outcome = "answered" | "malformed" | "cut-off" | "rate-limited" | "provider-error";
export type Promptid = string;
export type Promptsha256 = string;
export type Prompttokens = number;
export type Requests = number;
export type Maxtokens = number | null;
export type Temperature = number | null;
export type Thinking = string | null;
export type Statedlevel = ("low" | "medium" | "high") | null;
export type Notesfound = boolean;
export type Detail = string;
export type Kind1 = string;
export type Quote1 = string;
export type Reason =
  "quote-not-found" | "outside-version-window" | "empty-quote" | "symbol-not-in-quote" | "no-such-source";
export type Symbols1 = string[];
export type Version1 = string;
export type Refused = RefusedClaim[];
export type Updateid = string;
export type Abstainedreason = string;
export type Evidenceids = string[];
export type Level = ("low" | "medium" | "high") | null;
export type Rationale = string;
export type Ruleid = string;
export type Signal = "semver" | "changelog" | "usage";
export type Windows = string[];
export type Perupdate = ChangelogAnalysis[];
export type Promptid1 = string;
export type Promptsha2561 = string;
export type Refusalrate = number;
export type Ruleid1 = "changelog-rule/1";
export type Stopreason = string;
export type Stoppedonratelimit = boolean;
export type Version2 = number;

/**
 * The `changelog-report` artefact.
 */
export interface ChangelogReport {
  claimsRefused: Claimsrefused;
  claimsVerified: Claimsverified;
  generatedAt: Generatedat;
  modelId: Modelid;
  perUpdate: Perupdate;
  promptId: Promptid1;
  promptSha256: Promptsha2561;
  refusalRate: Refusalrate;
  ruleId: Ruleid1;
  stopReason: Stopreason;
  stoppedOnRateLimit: Stoppedonratelimit;
  version: Version2;
}
/**
 * The changelog signal for one update.
 */
export interface ChangelogAnalysis {
  claims: Claims;
  model: ModelCall | null;
  notesFound: Notesfound;
  refused: Refused;
  updateId: Updateid;
  vote: SignalVote;
  windows: Windows;
}
/**
 * A claim that was checked and holds: the quote is in the notes, in the window.
 */
export interface ChangelogClaim {
  id: Id;
  kind: Kind;
  quote: Quote;
  sourceUrl: Sourceurl;
  symbols: Symbols;
  version: Version;
}
/**
 * One call to the model, whatever came of it (NFR13).
 */
export interface ModelCall {
  completionTokens: Completiontokens;
  durationSeconds: Durationseconds;
  error: Error;
  modelId: Modelid1;
  outcome: Outcome;
  promptId: Promptid;
  promptSha256: Promptsha256;
  promptTokens: Prompttokens;
  requests: Requests;
  settings: ModelCallSettings;
  statedLevel: Statedlevel;
}
/**
 * The settings the call was made with, recorded because they change answers.
 */
export interface ModelCallSettings {
  maxTokens: Maxtokens;
  temperature: Temperature;
  thinking: Thinking;
}
/**
 * A claim the check refused, kept so the refusal rate is a result.
 */
export interface RefusedClaim {
  detail: Detail;
  kind: Kind1;
  quote: Quote1;
  reason: Reason;
  symbols: Symbols1;
  version: Version1;
}
/**
 * One signal's answer for one update, or its reason for having none.
 */
export interface SignalVote {
  abstainedReason: Abstainedreason;
  evidenceIds: Evidenceids;
  level: Level;
  rationale: Rationale;
  ruleId: Ruleid;
  signal: Signal;
}
