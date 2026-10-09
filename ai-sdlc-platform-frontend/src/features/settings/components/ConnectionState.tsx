import { RefreshCw } from "lucide-react";
import { retryConnections, type ConnectionsLoad } from "@/entities/settings";
import { Note } from "@/shared/ui/phase";
import { Button } from "@/shared/ui/primitives";

/** What stands in for a connection while the read is on its way, or after it failed. */
export function ConnectionsUnread({ load }: { load: ConnectionsLoad }) {
  if (load.status === "loading") return <Note>Reading your connections...</Note>;
  return (
    <div role="alert" className="space-y-2">
      <Note>
        Your connections could not be read, so whether this one is set up is not known:{" "}
        {load.error}
      </Note>
      <Button variant="outline" size="sm" onClick={() => retryConnections()}>
        <RefreshCw className="h-3.5 w-3.5" />
        Retry
      </Button>
    </div>
  );
}
