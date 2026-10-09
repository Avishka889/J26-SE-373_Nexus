import { Field, surface, useFieldClasses } from "@/shared/ui";
import { Server } from "lucide-react";
import { messageOf } from "@/lib/http";
import { useUiStore } from "@/store/ui";
import { useSettings, useSettingsActions } from "@/entities/settings";
import { cn } from "@/shared/utils/cn";
import { ConnectionSecret } from "./ConnectionSecret";
import { SettingsPanel } from "./SettingsPanel";
import { useConnection } from "../hooks/useConnection";

/**
 * Render, where a cloud release puts the backend.
 *
 * Only the account: an API key that stays on the server, and the region to
 * make services in. The platform makes each project's own web service with it,
 * on the free plan, and deploys the backend through Render's API itself, so the
 * key never goes to GitHub. Render builds only repositories its GitHub app can
 * read, which is the one thing to grant on Render's side.
 */
export function RenderTab() {
  const { status } = useConnection("render");
  const settings = useSettings();
  const { updateRenderSettings } = useSettingsActions();
  const addToast = useUiStore((st) => st.addToast);
  const { isDark, fieldClass } = useFieldClasses();

  return (
    <SettingsPanel
      icon={Server}
      title="Render backend"
      description="Where a cloud release puts the backend"
      status={status}
    >
      <p className={cn("text-sm", surface.faint(isDark))}>
        Each project gets its own web service on Render&apos;s free plan, made by the platform with
        this key on the project&apos;s first analysis with the cloud target. Give Render&apos;s
        GitHub app access to your repositories (All repositories covers each new one).
      </p>
      <ConnectionSecret
        provider="render"
        label="API key"
        hint="Create one in Render's Account Settings, API Keys. It stays on the server: the platform makes services and deploys with it, and it never goes to GitHub."
        placeholder="(never stored in the browser)"
      />
      <Field label="Region" hint="Where the platform makes each project's service">
        <select
          className={fieldClass}
          value={settings.render.region}
          onChange={(e) =>
            void updateRenderSettings({ region: e.target.value }).catch((error: unknown) =>
              addToast({ type: "error", title: "Not saved", message: messageOf(error) }),
            )
          }
        >
          <option value="oregon">Oregon (US West)</option>
          <option value="ohio">Ohio (US East)</option>
          <option value="virginia">Virginia (US East)</option>
          <option value="frankfurt">Frankfurt (EU)</option>
          <option value="singapore">Singapore (Asia)</option>
        </select>
      </Field>
    </SettingsPanel>
  );
}
