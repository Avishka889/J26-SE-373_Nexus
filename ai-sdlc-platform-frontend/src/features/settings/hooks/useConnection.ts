import {
  useConnections,
  useConnectionsLoad,
  type Connection,
  type ConnectionsLoad,
} from "@/entities/settings";
import { connectionStatus, type ConnectionStatus } from "../model/connection";

/**
 * One provider's stored credential and what is known about it.
 *
 * Until the connections were read, every provider read "Not connected" and
 * offered a token field; a failed read said nothing. Both invited a new token
 * over one that worked, so neither is said until the read has answered.
 */
export function useConnection(provider: string): {
  connection: Connection | undefined;
  status: ConnectionStatus;
  load: ConnectionsLoad;
} {
  const connection = useConnections().find((one) => one.provider === provider);
  const load = useConnectionsLoad();
  const status: ConnectionStatus =
    load.status === "loading"
      ? { label: "Checking...", tone: "default" }
      : load.status === "failed"
        ? { label: "Not known", tone: "warning" }
        : connectionStatus(connection);
  return { connection, status, load };
}
