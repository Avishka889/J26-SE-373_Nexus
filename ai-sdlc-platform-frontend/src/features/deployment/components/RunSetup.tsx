import { useState } from "react";
import { Button } from "@/shared/ui/primitives";
import type { ReleaseTarget, ReleaseTargetOption } from "../api/types";
import { packagesIn } from "../model/scope";

/**
 * Where the next analysis plans the release for.
 *
 * Asked before the run, because the plan, the pipeline and the candidate are
 * made for one target: it could be chosen only at the review, after all three,
 * so a first cloud release ran the analysis twice. A target that cannot be
 * used here says why, in the server's words.
 */
export function TargetChoice({
  targets,
  value,
  disabled,
  onChoose,
}: {
  targets: ReleaseTargetOption[];
  value: ReleaseTarget;
  disabled: boolean;
  onChoose: (target: ReleaseTarget) => void;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="tp-label">Release to</legend>
      <div className="mt-1.5 space-y-1.5">
        {targets.map((one) => (
          <label key={one.id} className="flex min-w-0 items-start gap-2 text-[13px]">
            <input
              type="radio"
              name="release-target"
              className="mt-0.5"
              value={one.id}
              checked={value === one.id}
              disabled={disabled || !one.usable}
              onChange={() => onChoose(one.id)}
            />
            <span className="min-w-0">
              {one.label}
              {!one.usable && one.reason && (
                <span className="tp-den block text-[12px]">Not available: {one.reason}.</span>
              )}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * What the next analysis looks at: every dependency, or the packages named.
 *
 * The route existed with no way to reach it from the page: Book Tracker's
 * first cloud release was scoped by calling the API by hand.
 */
export function ScopeField({
  packages,
  disabled,
  onSave,
}: {
  packages: string[];
  disabled: boolean;
  /** Resolves to whether the server took it. */
  onSave: (packages: string[]) => Promise<boolean>;
}) {
  const [text, setText] = useState(packages.join(", "));
  const [saving, setSaving] = useState(false);
  const changed = packagesIn(text).join(",") !== packages.join(",");
  return (
    <div className="min-w-0">
      <label className="block" htmlFor="analysis-scope">
        <span className="tp-label">Analyse</span>
        <span className="tp-den block text-[12px]">
          {packages.length === 0
            ? "Every dependency. Name packages to analyse only those."
            : `Only ${packages.join(", ")}. Clear the field to analyse every dependency.`}
        </span>
      </label>
      <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-2">
        <input
          id="analysis-scope"
          value={text}
          disabled={disabled || saving}
          onChange={(event) => setText(event.target.value)}
          placeholder="every dependency"
          className="min-w-0 flex-1 basis-48 rounded-md border border-[color:var(--tp-line-strong)] bg-transparent px-2 py-1 text-[13px] outline-none focus:border-blue-500/50"
        />
        <Button
          variant="outline"
          size="sm"
          busy={saving}
          disabled={disabled || !changed}
          onClick={async () => {
            setSaving(true);
            try {
              await onSave(packagesIn(text));
            } finally {
              setSaving(false);
            }
          }}
        >
          Save
        </Button>
      </div>
    </div>
  );
}
