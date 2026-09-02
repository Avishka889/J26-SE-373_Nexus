import { useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import { NAME_LIMIT, projectsApi } from "@/entities/project";
import { messageOf } from "@/lib/http";
import { useUiStore } from "@/store/ui";
import { cn } from "@/shared/utils/cn";

/**
 * The project's name, and the one place it can be changed.
 *
 * Names could not be changed at all: the server took a new name on its PATCH,
 * and nothing on any page sent one, so a project named from the first line of
 * its requirements kept that name for good. Enter or Save renames; Escape or
 * Cancel leaves it as it was; a refusal says why and keeps the edit open.
 */
export function ProjectTitle({
  projectId,
  name,
  isDark,
}: {
  projectId: string;
  name: string;
  isDark: boolean;
}) {
  const addToast = useUiStore((s) => s.addToast);
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const next = (draft ?? "").replace(/\s+/g, " ").trim();
  const canSave = next.length > 0 && next.length <= NAME_LIMIT && next !== name && !saving;

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      await projectsApi.update(projectId, { name: next });
      setDraft(null);
    } catch (error) {
      addToast({ type: "error", title: "The project was not renamed", message: messageOf(error) });
    } finally {
      setSaving(false);
    }
  };

  const heading = cn(
    "text-xl font-semibold tracking-tight md:text-2xl",
    isDark ? "text-white" : "text-slate-900",
  );
  const iconButton = cn(
    "flex h-8 w-8 items-center justify-center rounded-lg transition-colors",
    isDark ? "text-slate-400 hover:bg-white/5 hover:text-white" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900",
  );

  if (draft === null) {
    return (
      <div className="flex min-w-0 items-center gap-1">
        <h1 className={cn(heading, "min-w-0 break-words")}>{name}</h1>
        <button
          type="button"
          aria-label="Rename the project"
          title="Rename the project"
          className={iconButton}
          onClick={() => setDraft(name)}
        >
          <Pencil aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <form
      className="flex min-w-0 flex-wrap items-center gap-1"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <input
        aria-label="Project name"
        autoFocus
        maxLength={NAME_LIMIT}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setDraft(null);
        }}
        className={cn(
          heading,
          "min-w-0 flex-1 rounded-lg border bg-transparent px-2 py-0.5 outline-none focus:border-blue-500/60",
          isDark ? "border-white/15" : "border-slate-300",
        )}
      />
      <button type="submit" aria-label="Save the name" title="Save the name" disabled={!canSave} className={cn(iconButton, "disabled:opacity-40")}>
        <Check aria-hidden="true" className="h-4 w-4" />
      </button>
      <button type="button" aria-label="Cancel renaming" title="Cancel" className={iconButton} onClick={() => setDraft(null)}>
        <X aria-hidden="true" className="h-4 w-4" />
      </button>
    </form>
  );
}
