import type { ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import type { SettingsLoad } from "@/entities/settings";
import { Note, Spinner } from "@/shared/ui";
import { Button } from "@/shared/ui/primitives";

/**
 * The settings, once the server's have arrived.
 *
 * Before they arrive the store holds the defaults, and a tab that showed them
 * showed empty fields that filled themselves a second later: on the Database
 * tab that read as fields clearing on their own, and a field typed into in that
 * second was then saved over what the server held. So nothing editable shows
 * until the server has answered, and a read that failed says so.
 */
export function SettingsGate({
  load,
  onRetry,
  children,
}: {
  load: SettingsLoad;
  onRetry: () => void;
  children: ReactNode;
}) {
  if (load.loaded) return <>{children}</>;
  if (load.error) {
    return (
      <Note>
        Your settings could not be read from the server ({load.error}), so none
        are shown, rather than empty fields that look like yours.
        <span className="mt-2 block">
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="h-4 w-4" />
            Try again
          </Button>
        </span>
      </Note>
    );
  }
  return (
    <div className="flex items-center gap-2 py-6 text-sm" role="status">
      <Spinner size="sm" decorative />
      Reading your settings
    </div>
  );
}
