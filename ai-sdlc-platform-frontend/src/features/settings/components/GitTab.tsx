import { useState } from "react";
import { Field, useFieldClasses } from "@/shared/ui";
import { GitBranch, Link2, RefreshCw, Shield, Unlink } from "lucide-react";
import { messageOf } from "@/lib/http";
import { useUiStore } from "@/store/ui";
import { useConnectionsActions } from "@/entities/settings";
import { cn } from "@/shared/utils/cn";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { Badge, Button } from "@/shared/ui/primitives";
import { verdictSentence, verdictTitle, verdictTone } from "../model/connection";
import { ConnectionsUnread } from "./ConnectionState";
import { useConnection } from "../hooks/useConnection";
import { SettingsPanel } from "./SettingsPanel";

/**
 * The GitHub connection, over the credential store.
 *
 * The token goes to the server once and is never echoed back: what this tab
 * shows afterwards is that a connection exists, the scopes the check read,
 * and what the check found, in words. Disconnecting asks first, since nothing
 * brings a deleted token back.
 *
 * GitHub only, and no default organisation: GitLab and Bitbucket were offered
 * and nothing could use them, and repositories are created in the account
 * that owns the token whatever the organisation field said.
 */
export function GitTab() {
  const addToast = useUiStore((s) => s.addToast);
  const { connection: github, status, load } = useConnection("github");
  const { connect, revoke, probe } = useConnectionsActions();
  const { isDark, fieldClass } = useFieldClasses();

  const [token, setToken] = useState("");
  const [busy, setBusy] = useState<"checking" | "disconnecting" | "connecting" | null>(null);
  const [confirming, setConfirming] = useState(false);

  const run = async (
    which: "checking" | "disconnecting" | "connecting",
    work: () => Promise<unknown>,
    failure: string,
  ) => {
    setBusy(which);
    try {
      await work();
    } catch (error) {
      addToast({ type: "error", title: failure, message: messageOf(error) });
    } finally {
      setBusy(null);
    }
  };

  const footer =
    load.status !== "loaded" ? undefined : github ? (
      <>
        <Button
          variant="outline"
          busy={busy === "checking"}
          disabled={busy !== null}
          onClick={() =>
            run(
              "checking",
              async () => {
                const refreshed = await probe("github");
                addToast({
                  type: verdictTone(refreshed.probe?.verdict),
                  title: `GitHub: ${verdictTitle(refreshed.probe?.verdict)}`,
                  message: refreshed.probe?.reason ?? "",
                });
              },
              "The check failed",
            )
          }
        >
          <RefreshCw className="h-4 w-4" />
          {busy === "checking" ? "Checking..." : "Check it again"}
        </Button>
        <Button variant="outline" disabled={busy !== null} onClick={() => setConfirming(true)}>
          <Unlink className="h-4 w-4" />
          Disconnect
        </Button>
      </>
    ) : (
      <Button
        variant="primary"
        busy={busy === "connecting"}
        disabled={busy !== null || token.trim().length === 0}
        onClick={() =>
          run(
            "connecting",
            async () => {
              const created = await connect("github", token.trim());
              setToken("");
              addToast({
                type: verdictTone(created.probe?.verdict),
                title: `GitHub connected: ${verdictTitle(created.probe?.verdict)}`,
                message: created.probe?.reason ?? "Token stored encrypted.",
              });
            },
            "Connecting failed",
          )
        }
      >
        <Link2 className="h-4 w-4" />
        {busy === "connecting" ? "Connecting and checking..." : "Connect"}
      </Button>
    );

  return (
    <SettingsPanel
      icon={GitBranch}
      title="Git integration"
      description="GitHub, for the repositories code generation pushes to. They are created in the account that owns the token."
      status={status}
      footer={footer}
    >
      {load.status !== "loaded" ? (
        <ConnectionsUnread load={load} />
      ) : github ? (
        <div className="space-y-3">
          <Field
            label="What the token can do"
            hint="Read by the check; the value itself is never shown"
          >
            <div className="flex flex-wrap items-center gap-2">
              {github.scopes.length > 0 ? (
                github.scopes.map((scope) => (
                  <Badge key={scope} variant="default" className="font-mono text-xs">
                    {scope}
                  </Badge>
                ))
              ) : (
                <span className={cn("text-sm", isDark ? "text-slate-400" : "text-slate-500")}>
                  {github.tokenKind === "fine-grained"
                    ? "A fine grained token does not publish its permissions."
                    : "No scopes reported yet."}
                </span>
              )}
            </div>
          </Field>
          {github.probe && (
            <p className={cn("text-sm", isDark ? "text-slate-400" : "text-slate-500")}>
              {verdictSentence(github.probe)}
            </p>
          )}
        </div>
      ) : (
        <Field
          label="Personal access token"
          hint="Stored encrypted on the server and never shown again. Classic token with the repo and workflow scopes."
        >
          {(control) => (
            <div className="relative">
              <Shield
                className={cn(
                  "absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2",
                  isDark ? "text-slate-400" : "text-slate-500",
                )}
              />
              {/* Not a sign in: see ConnectionSecret for what "off" let happen. */}
              <input
                {...control}
                type="password"
                autoComplete="new-password"
                className={cn(fieldClass, "pl-10 font-mono text-[13px]")}
                placeholder="ghp_(never stored in the browser)"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </div>
          )}
        </Field>
      )}
      {confirming && (
        <ConfirmDialog
          title="Disconnect GitHub?"
          body="The token is deleted from the server and cannot be brought back. Code generation stops pushing to GitHub until a new token is connected."
          confirmLabel="Disconnect"
          isDark={isDark}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            void run(
              "disconnecting",
              async () => {
                await revoke("github");
                addToast({ type: "info", title: "GitHub disconnected", message: "The token was deleted." });
              },
              "Disconnecting failed",
            );
          }}
        />
      )}
    </SettingsPanel>
  );
}
