import { useState } from "react";
import { Field, surface, useFieldClasses } from "@/shared/ui";
import { RefreshCw, Shield, Trash2 } from "lucide-react";
import { messageOf } from "@/lib/http";
import { useUiStore } from "@/store/ui";
import { useConnectionsActions } from "@/entities/settings";
import { cn } from "@/shared/utils/cn";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { Button } from "@/shared/ui/primitives";
import { verdictSentence, verdictTitle, verdictTone } from "../model/connection";
import { ConnectionsUnread } from "./ConnectionState";
import { useConnection } from "../hooks/useConnection";

/**
 * One provider secret over the credential store, kept the way the GitHub tab
 * keeps its token.
 *
 * The value goes to the server once, is stored encrypted there and never comes
 * back. Afterwards the block shows only that it exists and what the last check
 * found, in words, and it can be checked again or removed; removing asks first,
 * since nothing brings a deleted token back. Nothing is kept in the browser but
 * what is being typed, and no field is offered until the connections are read.
 */
export function ConnectionSecret({
  provider,
  label,
  hint,
  placeholder,
  beforeCheck,
}: {
  /** The connections store's name for it: `vercel`, `render`, `render-deploy-hook`. */
  provider: string;
  label: string;
  hint: string;
  placeholder: string;
  /**
   * Run before the secret is saved or checked: the Atlas check reads the
   * identifiers beside it, and one still being typed has to reach the server first.
   */
  beforeCheck?: () => Promise<unknown>;
}) {
  const addToast = useUiStore((s) => s.addToast);
  const { connection: stored, load } = useConnection(provider);
  const { connect, revoke, probe } = useConnectionsActions();
  const { isDark, fieldClass } = useFieldClasses();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<"checking" | "removing" | "saving" | null>(null);
  const [confirming, setConfirming] = useState(false);

  const run = async (
    which: "checking" | "removing" | "saving",
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

  if (load.status !== "loaded") {
    return (
      <div data-connection={provider}>
        <span className={cn("mb-1.5 block text-sm font-medium", isDark ? "text-slate-200" : "text-slate-700")}>
          {label}
        </span>
        <ConnectionsUnread load={load} />
      </div>
    );
  }

  if (stored) {
    // Not a Field: a label forwards a click on its text to its first control,
    // and here that would be a button.
    return (
      <div data-connection={provider}>
        <span
          className={cn(
            "mb-1.5 block text-sm font-medium",
            isDark ? "text-slate-200" : "text-slate-700",
          )}
        >
          {label}
        </span>
        <div className="space-y-2">
          <p className={cn("text-sm", isDark ? "text-slate-400" : "text-slate-500")}>
            {stored.probe ? verdictSentence(stored.probe) : "Saved, and not checked yet."}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              busy={busy === "checking"}
              disabled={busy !== null}
              onClick={() =>
                run(
                  "checking",
                  async () => {
                    await beforeCheck?.();
                    const refreshed = await probe(provider);
                    addToast({
                      type: verdictTone(refreshed.probe?.verdict),
                      title: `${label}: ${verdictTitle(refreshed.probe?.verdict)}`,
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
            <Button
              variant="outline"
              size="sm"
              disabled={busy !== null}
              onClick={() => setConfirming(true)}
            >
              <Trash2 className="h-4 w-4" />
              Remove
            </Button>
          </div>
        </div>
        <span className={cn("mt-1.5 block text-xs", surface.faint(isDark))}>
          Stored encrypted on the server; the value is never shown again
        </span>
        {confirming && (
          <ConfirmDialog
            title={`Remove the ${label.toLowerCase()}?`}
            body="It is deleted from the server and cannot be shown or brought back. Anything that uses it stops working until a new one is saved."
            confirmLabel="Remove the token"
            isDark={isDark}
            onCancel={() => setConfirming(false)}
            onConfirm={() => {
              setConfirming(false);
              void run(
                "removing",
                async () => {
                  await revoke(provider);
                  addToast({ type: "info", title: `${label} removed`, message: "It was deleted." });
                },
                "Removing it failed",
              );
            }}
          />
        )}
      </div>
    );
  }

  // The input alone in its Field, which holds exactly one control; the button
  // that saves it sits beside the Field, not inside its label.
  return (
    <div
      className="flex flex-wrap items-start gap-2 sm:flex-nowrap"
      data-connection={provider}
    >
      <Field label={label} hint={hint} className="min-w-0 flex-1">
        {(control) => (
          <div className="relative">
            <Shield
              className={cn(
                "absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2",
                isDark ? "text-slate-400" : "text-slate-500",
              )}
            />
            {/* "new-password", not "off": a browser's password manager ignores
              "off" on a password field, takes the form for a sign in, and fills
              the text field above it with the saved email (the Atlas tab's
              client ID met exactly that) and this one with a saved password. */}
            <input
              {...control}
              type="password"
              autoComplete="new-password"
              className={cn(fieldClass, "pl-10 font-mono text-[13px]")}
              placeholder={placeholder}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
        )}
      </Field>
      <Button
        variant="primary"
        className="sm:mt-7"
        busy={busy === "saving"}
        disabled={busy !== null || value.trim().length === 0}
        onClick={() =>
          run(
            "saving",
            async () => {
              await beforeCheck?.();
              const created = await connect(provider, value.trim());
              setValue("");
              addToast({
                type: verdictTone(created.probe?.verdict),
                title: `${label} saved: ${verdictTitle(created.probe?.verdict)}`,
                message: created.probe?.reason ?? "Stored encrypted.",
              });
            },
            "Saving it failed",
          )
        }
      >
        {busy === "saving" ? "Saving and checking..." : "Save"}
      </Button>
    </div>
  );
}
