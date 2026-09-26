/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Candidatehash = string;
export type Codeversion = number;
export type Bytes = number;
export type Path = string;
export type Purpose = "workflow" | "container" | "hosting" | "orchestration" | "ignore" | "lockfile" | "fingerprint";
export type Secretsreferenced = string[];
export type Sha256 = string;
export type Templateid = string;
/**
 * Every validator that applies to it ran, and passed.
 */
export type Valid = boolean;
export type Findings = string[];
export type Outcome = "passed" | "failed" | "not-run";
export type Reason = string;
export type Schemaretrieved = string;
export type Schemaurl = string;
export type Tool = string;
export type Validator = "json-schema" | "yaml-parse" | "actionlint" | "hadolint" | "kubeconform" | "secret-scan";
export type Validations = FileValidation[];
export type Files = PipelineFile[];
export type Generatedat = string;
export type Kubernetes = "generated" | "skipped";
export type Kubernetesreason = string;
export type Backenddir = string | null;
/**
 * @minItems 1
 */
export type Evidence = [string, ...string[]];
export type Frontenddir = string | null;
export type Kind = "one-process" | "split" | "backend-only" | "frontend-only";
export type Servesfrontendfrombackend = boolean;
export type Shareddirs = string[];
export type Reason1 = string;
export type Stackid = string;
export type Supported = boolean;
/**
 * NFR5: a supported stack whose every generated file is valid.
 */
export type Valid1 = boolean;
export type Version = number;

/**
 * The `pipeline-config` artefact.
 */
export interface PipelineConfig {
  candidateHash: Candidatehash;
  codeVersion: Codeversion;
  files: Files;
  generatedAt: Generatedat;
  kubernetes: Kubernetes;
  kubernetesReason: Kubernetesreason;
  stack: StackSupport;
  valid: Valid1;
  version: Version;
}
/**
 * One generated file.
 */
export interface PipelineFile {
  bytes: Bytes;
  path: Path;
  purpose: Purpose;
  secretsReferenced: Secretsreferenced;
  sha256: Sha256;
  templateId: Templateid;
  valid: Valid;
  validations: Validations;
}
/**
 * One validator's verdict on one file.
 */
export interface FileValidation {
  findings: Findings;
  outcome: Outcome;
  reason: Reason;
  schemaRetrieved: Schemaretrieved;
  schemaUrl: Schemaurl;
  tool: Tool;
  validator: Validator;
}
/**
 * Whether this stack has validated templates, and if not, why (FR14).
 */
export interface StackSupport {
  layout: ArchitecturalLayout | null;
  reason: Reason1;
  stackId: Stackid;
  supported: Supported;
}
/**
 * How the project is laid out, and the facts that decided it.
 */
export interface ArchitecturalLayout {
  backendDir: Backenddir;
  evidence: Evidence;
  frontendDir: Frontenddir;
  kind: Kind;
  servesFrontendFromBackend: Servesfrontendfrombackend;
  sharedDirs: Shareddirs;
}
