import { Field, useFieldClasses } from "@/shared/ui";
import { User } from "lucide-react";
import { messageOf } from "@/lib/http";
import { useUiStore } from "@/store/ui";
import { useSettings, useSettingsActions } from "@/entities/settings";
import { ProfilePhotoEditor } from "@/shared/ui/brand/UserAvatar";
import { cn } from "@/shared/utils/cn";
import { SettingsPanel } from "./SettingsPanel";
import { useDebouncedText } from "../useDebouncedText";

/**
 * The account as others see it: a name and a photo.
 *
 * The name saves once the typing stops. It saved on every keystroke and the
 * field took each answer back, so typed characters dropped; and the "Save
 * changes" button beside it only showed a toast. The workspace name went with
 * it: nothing read it, though its hint said the sidebar did.
 */
export function ProfileTab() {
  const addToast = useUiStore((s) => s.addToast);
  const settings = useSettings();
  const { updateProfile } = useSettingsActions();
  const { isDark, fieldClass } = useFieldClasses();
  const [name, setName] = useDebouncedText(settings.profile.name, (next) =>
    updateProfile({ name: next }),
  );

  // Said once the server has kept it, not before.
  const savePhoto = async (avatarUrl: string | null) => {
    try {
      await updateProfile({ avatarUrl });
      addToast(
        avatarUrl
          ? { type: "success", title: "Photo updated" }
          : { type: "info", title: "Photo removed" },
      );
    } catch (error) {
      addToast({ type: "error", title: "Photo not saved", message: messageOf(error) });
    }
  };

  return (
    <SettingsPanel
      icon={User}
      title="Profile"
      description="How you appear across the platform. Changes save as you make them."
    >
      <ProfilePhotoEditor
        isDark={isDark}
        name={settings.profile.name}
        email={settings.profile.email}
        avatarUrl={settings.profile.avatarUrl}
        onAvatarChange={(dataUrl) => void savePhoto(dataUrl)}
        onAvatarRemove={() => void savePhoto(null)}
        onError={(title, message) => addToast({ type: "error", title, message })}
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Full name">
          <input className={fieldClass} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Email" hint="The email you sign in with. It is your account's, so it is not changed here.">
          <input
            type="email"
            readOnly
            aria-readonly="true"
            className={cn(fieldClass, "cursor-default opacity-80")}
            value={settings.profile.email}
          />
        </Field>
      </div>
    </SettingsPanel>
  );
}
