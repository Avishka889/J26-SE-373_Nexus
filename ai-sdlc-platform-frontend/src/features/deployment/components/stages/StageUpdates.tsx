import { Boxes, PackageSearch, ShieldOff } from "lucide-react";
import { Chip, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { DeploySnapshot } from "../../api/types";
import { EmptyNote, Facts, Mono } from "../bits";
import { shortHash } from "../../model/view";

/**
 * Dependency Updates: what the registries offered, and what could not be assessed.
 *
 * A short list of updates has to be visibly short rather than possibly
 * truncated, so the stage says what was asked and of whom before it says what
 * came back, and an update that could not be assessed is a row with its
 * reason (FR3), never a silent gap.
 */
export function StageUpdates({ snapshot }: { snapshot: DeploySnapshot }) {
  const updates = snapshot.updates;
  if (!updates) return <EmptyNote>No registry has been asked yet at this deploy version.</EmptyNote>;
  const answered = updates.queried.filter((one) => one.status !== null && one.status < 400).length;

  return (
    <div className="space-y-4">
      <StageSection id="updates-checked">
        <Panel
          icon={<PackageSearch className="h-4 w-4 text-blue-400" />}
          label="What was checked"
          title="The exact dependency set this analysis starts from, and every registry question it asked."
        >
          <Facts
            rows={[
              ["Repository", updates.target === "generated" ? "The generated application" : updates.target],
              [
                "Baseline lockfile",
                updates.baseline ? (
                  <>
                    <Mono>{updates.baseline.lockfilePath}</Mono>, sha256{" "}
                    <Mono>{shortHash(updates.baseline.lockfileSha256)}</Mono>
                  </>
                ) : (
                  "not pinned"
                ),
              ],
              [
                "Packages in the lockfile",
                updates.baseline
                  ? `${updates.baseline.packages}, of which ${updates.baseline.direct} are direct`
                  : "unknown",
              ],
              ["Pinned with", updates.baseline ? <Mono>{updates.baseline.resolvedBy}</Mono> : "nothing"],
              ["Registry questions", `${updates.queried.length} asked, ${answered} answered`],
              [
                "Already up to date",
                updates.upToDate.length > 0 ? updates.upToDate.join(", ") : "none named",
              ],
            ]}
          />
        </Panel>
      </StageSection>

      <StageSection id="updates-available">
        <Panel
          icon={<Boxes className="h-4 w-4 text-blue-400" />}
          label="Available updates"
          title={`${updates.updates.length} newer releases, each assessed on the stages that follow.`}
        >
          {updates.updates.length === 0 ? (
            <EmptyNote>Every dependency the registries know is at its newest release.</EmptyNote>
          ) : (
            <ul className="divide-y divide-[color:var(--tp-line)]">
              {updates.updates.map((update) => (
                <li key={update.id} className="flex flex-wrap items-start gap-x-4 gap-y-1.5 py-2.5">
                  <div className="min-w-0 flex-1 basis-56">
                    <p className="break-words text-[13px] font-semibold text-[color:var(--tp-ink)]">
                      {update.package}
                    </p>
                    <p className="tp-den mt-0.5 break-words">
                      <Mono>{update.fromVersion}</Mono> to <Mono>{update.toVersion}</Mono> in{" "}
                      <Mono>{update.manifestPath}</Mono>
                      {update.alsoDeclaredIn.map((path) => (
                        <span key={path}>
                          {" "}and <Mono>{path}</Mono>
                        </span>
                      ))}
                    </p>
                  </div>
                  <span className="inline-flex flex-wrap items-center gap-1.5">
                    <Chip>{update.change}</Chip>
                    <Chip>{update.scope}</Chip>
                    <Chip tone={update.notes.length > 0 ? "info" : "neutral"}>
                      {update.notes.length > 0
                        ? `${update.notes.length} release note source${update.notes.length === 1 ? "" : "s"}`
                        : "no release notes"}
                    </Chip>
                    {update.flags.map((flag) => (
                      <Chip key={flag} tone="caution">
                        {flag}
                      </Chip>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>

      <StageSection id="updates-rejected">
        <Panel
          icon={<ShieldOff className="h-4 w-4 text-blue-400" />}
          label="Could not assess"
          title="Refused with the reason, rather than guessed at."
        >
          {updates.rejected.length === 0 ? (
            <EmptyNote>Every update the registries offered could be assessed.</EmptyNote>
          ) : (
            <ul className="space-y-3">
              {updates.rejected.map((rejected) => (
                <li key={`${rejected.manifestPath}:${rejected.package}`} className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-[13px] font-semibold text-[color:var(--tp-ink)]">
                    <span className="break-words">{rejected.package}</span>
                    <Chip tone="caution">{rejected.reason}</Chip>
                  </p>
                  <p className="tp-prose mt-1 break-words">{rejected.detail}</p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>
    </div>
  );
}
