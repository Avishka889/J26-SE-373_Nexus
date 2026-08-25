/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Model = string;
export type Provider = string;
export type Temperature = number;
export type Code = ("off" | "low" | "high" | "max") | null;
export type Deployment = ("off" | "low" | "high" | "max") | null;
export type Design = ("off" | "low" | "high" | "max") | null;
export type Testing = ("off" | "low" | "high" | "max") | null;
export type Clientid = string;
export type Cluster = string;
export type Connected = boolean;
export type Projectid = string;
export type Provider1 = "neon" | "mongodb_atlas";
export type Connected1 = boolean;
export type Defaultorg = string;
export type Provider2 = string;
export type Scopes = string[];
export type Avatarurl = string | null;
export type Email = string;
export type Name = string;
export type Workspace = string;
export type Connected2 = boolean;
export type Origin = string;
export type Region = string;
export type Serviceid = string;
export type Connected3 = boolean;
export type Orgid = string;
export type Origin1 = string;
export type Projectid1 = string;
export type Team = string;

export interface SettingsState {
  ai: AiSettings;
  database: DatabaseSettings;
  git: GitSettings;
  profile: ProfileSettings;
  render: RenderSettings;
  vercel: VercelSettings;
}
export interface AiSettings {
  model: Model;
  provider: Provider;
  temperature: Temperature;
  thinking: PhaseThinking;
}
/**
 * How hard each phase is asked to think, as this account chose it.
 *
 * None is no choice: the phase thinks as the platform is configured (off
 * unless configured). A choice applies from the next run, and a run keeps the
 * level it started at for its whole life, regenerations included.
 */
export interface PhaseThinking {
  code: Code;
  deployment: Deployment;
  design: Design;
  testing: Testing;
}
/**
 * Where a cloud release keeps each app's records: the account's Atlas cluster.
 *
 * Identifiers only. The service account's secret is a connection (`atlas`),
 * and each project's database, user and password are made by the platform.
 */
export interface DatabaseSettings {
  clientId: Clientid;
  cluster: Cluster;
  connected: Connected;
  projectId: Projectid;
  provider: Provider1;
}
export interface GitSettings {
  connected: Connected1;
  defaultOrg: Defaultorg;
  provider: Provider2;
  scopes: Scopes;
}
export interface ProfileSettings {
  avatarUrl: Avatarurl;
  email: Email;
  name: Name;
  workspace: Workspace;
}
export interface RenderSettings {
  connected: Connected2;
  origin: Origin;
  region: Region;
  serviceId: Serviceid;
}
export interface VercelSettings {
  connected: Connected3;
  orgId: Orgid;
  origin: Origin1;
  projectId: Projectid1;
  team: Team;
}
