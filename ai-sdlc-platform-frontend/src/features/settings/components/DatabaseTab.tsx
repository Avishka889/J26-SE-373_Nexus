import { Field, surface, useFieldClasses } from "@/shared/ui";
import { Database } from "lucide-react";
import { useSettings, useSettingsActions } from "@/entities/settings";
import { cn } from "@/shared/utils/cn";
import { useDebouncedText } from "../useDebouncedText";
import { ConnectionSecret } from "./ConnectionSecret";
import { SettingsPanel } from "./SettingsPanel";
import { useConnection } from "../hooks/useConnection";

/**
 * MongoDB Atlas, where a cloud release keeps each generated app's records.
 *
 * Only the account: the Atlas project and the cluster the account made once,
 * and a service account to work with them, whose client ID is an identifier
 * kept here and whose secret goes to the credential store like every token.
 * Each project's own database, and a database user for that database alone,
 * are made by the platform, which sets the app's connection string on its
 * Render service; no password or connection string is ever typed here.
 */
export function DatabaseTab() {
  const { status } = useConnection("atlas");
  const settings = useSettings();
  const { updateDatabaseSettings } = useSettingsActions();
  const { isDark, fieldClass } = useFieldClasses();

  // Saved when the typing stops, not on every keystroke: see the hook.
  const [projectId, setProjectId, flushProjectId] = useDebouncedText(settings.database.projectId, (next) =>
    updateDatabaseSettings({ provider: "mongodb_atlas", projectId: next.trim() }),
  );
  const [cluster, setCluster, flushCluster] = useDebouncedText(settings.database.cluster, (next) =>
    updateDatabaseSettings({ provider: "mongodb_atlas", cluster: next.trim() }),
  );
  const [clientId, setClientId, flushClientId] = useDebouncedText(settings.database.clientId, (next) =>
    updateDatabaseSettings({ provider: "mongodb_atlas", clientId: next.trim() }),
  );

  return (
    <SettingsPanel
      icon={Database}
      title="MongoDB Atlas database"
      description="Where a cloud release keeps each app's records"
      status={status}
    >
      <p className={cn("text-sm", surface.faint(isDark))}>
        Each project gets its own database on this cluster, and a database user that can reach
        that database alone, made by the platform on the project&apos;s first analysis with the
        cloud target. Without a connection, a released app keeps its records in memory, so a
        restart or a new release starts it empty.
      </p>
      <Field
        label="Atlas project ID"
        hint="The 24 character id after /v2/ in Atlas's address bar while you are in the project, or at the top of its Project Settings"
      >
        <input
          autoComplete="off"
          className={cn(fieldClass, "font-mono text-[13px]")}
          placeholder="66f0c0ffee0123456789abcd"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
        />
      </Field>
      <Field label="Cluster" hint="The cluster's name in that project; the free M0 tier is enough">
        <input
          autoComplete="off"
          className={fieldClass}
          placeholder="Cluster0"
          value={cluster}
          onChange={(e) => setCluster(e.target.value)}
        />
      </Field>
      <Field
        label="Service account client ID"
        hint="In Atlas: Project Identity & Access, Create Application, Service Account, with Project Read Only and Project Database Access Admin and nothing more. Its Client ID, not your email."
      >
        <input
          autoComplete="off"
          className={cn(fieldClass, "font-mono text-[13px]")}
          placeholder="mdb_sa_id_..."
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
        />
      </Field>
      <ConnectionSecret
        provider="atlas"
        label="Service account secret"
        hint="Shown once when the service account is made. Fill in the fields above first: the check reads them. Stored encrypted on the server and never shown again."
        placeholder="(never stored in the browser)"
        beforeCheck={() => Promise.all([flushProjectId(), flushCluster(), flushClientId()])}
      />
      <p className={cn("text-sm", surface.faint(isDark))}>
        In Atlas, Database &amp; Network Access, IP Access List: let Render reach the cluster by
        adding the ranges a Render service lists under Connect, Outbound (or 0.0.0.0/0).
      </p>
    </SettingsPanel>
  );
}
