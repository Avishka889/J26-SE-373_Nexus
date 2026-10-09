import { useDocumentTitle } from "@/shared/hooks";
import { useUiStore } from "@/store/ui";
import { useCreateFromPrompt } from "../hooks";
import { useSettings } from "@/entities/settings";
import { ProjectCreatePrompt } from "../components/ProjectCreatePrompt";

export function NewProject() {
  useDocumentTitle("New project");
  const theme = useUiStore((s) => s.theme);
  const settings = useSettings();
  const handleCreate = useCreateFromPrompt();
  const isDark = theme === "dark";
  const firstName = settings.profile.name.split(" ")[0] || "there";

  return (
    <div className="relative flex min-h-full w-full flex-col justify-center px-4 pb-12 pt-8 sm:px-6 md:px-8 md:pt-14">
      <ProjectCreatePrompt firstName={firstName} isDark={isDark} onSubmit={handleCreate} autoFocus />
    </div>
  );
}
