import { Field, surface, useFieldClasses } from "@/shared/ui";
import { Cloud } from "lucide-react";
import { useSettings, useSettingsActions } from "@/entities/settings";
import { cn } from "@/shared/utils/cn";
import { useDebouncedText } from "../useDebouncedText";
import { ConnectionSecret } from "./ConnectionSecret";
import { SettingsPanel } from "./SettingsPanel";
import { useConnection } from "../hooks/useConnection";

/**
 * Vercel, where a cloud release puts the frontend.
 *
 * Only the account: a token, kept by the credential store like the GitHub
 * token, and the team to work in. Each project's own Vercel project, its ids
 * and its address are made by the platform on the project's first analysis with
 * the cloud target, so nothing here names one project.
 */
export function VercelTab() {
  const { status } = useConnection("vercel");
  const settings = useSettings();
  const { updateVercelSettings } = useSettingsActions();
  const { isDark, fieldClass } = useFieldClasses();

  // Saved when the typing stops, not on every keystroke: see the hook.
  const [team, setTeam] = useDebouncedText(settings.vercel.team, (next) =>
    updateVercelSettings({ team: next.trim() }),
  );

  return (
    <SettingsPanel
      icon={Cloud}
      title="Vercel frontend"
      description="Where a cloud release puts the frontend"
      status={status}
    >
      <p className={cn("text-sm", surface.faint(isDark))}>
        Each project gets its own Vercel project, made by the platform with this token on the
        project&apos;s first analysis with the cloud target.
      </p>
      <ConnectionSecret
        provider="vercel"
        label="Access token"
        hint="Create one at vercel.com/account/tokens, scoped to the account or team the projects belong in. Stored encrypted on the server and never shown again."
        placeholder="(never stored in the browser)"
      />
      <Field
        label="Team / scope"
        hint="The team to make projects in, as its id (team_...) or slug; leave blank for a personal account"
      >
        <input
          className={fieldClass}
          placeholder="your-team"
          value={team}
          onChange={(e) => setTeam(e.target.value)}
        />
      </Field>
    </SettingsPanel>
  );
}
