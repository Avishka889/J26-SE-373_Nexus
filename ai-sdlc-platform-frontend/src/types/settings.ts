/**
 * Settings types, re-exported from the generated contract package.
 *
 * The wire shape is secret free by design: no token, api key, password or
 * connection string field exists on it, so a credential cannot end up in the
 * settings store by construction. Credentials live behind /connections, and
 * the UI shows only that one exists and what its probe learned.
 */

import type { DatabaseSettings } from "@sdlc/contracts-ts";

export type {
  AiSettings,
  DatabaseSettings,
  GitSettings,
  ProfileSettings,
  RenderSettings,
  SettingsState,
  VercelSettings,
} from "@sdlc/contracts-ts";

export type DatabaseProvider = DatabaseSettings["provider"];
