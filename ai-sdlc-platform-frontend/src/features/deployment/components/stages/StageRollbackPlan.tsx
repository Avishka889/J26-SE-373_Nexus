import { ListOrdered, RotateCcw } from "lucide-react";
import { Chip, Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { DeploySnapshot } from "../../api/types";
import { EmptyNote, Facts, Mono } from "../bits";
import { shortHash } from "../../model/view";
import { formatWhen } from "@/shared/utils/time";

/**
 * Rollback Plan: where a rollback would go, and how restored is proved.
 *
 * A rollback redeploys the recorded verified release, never a provider's
 * "previous deploy" button, and it is reported restored only when that
 * release's fingerprint is served again and health and smoke answer. It never
 * starts without a person's approval (FR20), which the plan states as its
 * first fact rather than its last.
 */
export function StageRollbackPlan({
  snapshot,
  packageOf,
}: {
  snapshot: DeploySnapshot;
  packageOf: (updateId: string) => string;
}) {
  const plan = snapshot.rollback;
  if (!plan) return <EmptyNote>No rollback has been planned at this deploy version.</EmptyNote>;
  const target = plan.restoreTarget;

  return (
    <div className="space-y-4">
      <StageSection id="rollback-target">
        <Panel
          icon={<RotateCcw className="h-4 w-4 text-blue-400" />}
          label="Restore target"
          title={
            plan.restorable && target
              ? `Deploy version ${target.deployVersion}, the verified release this candidate would be rolled back to.`
              : `Nothing to restore: ${plan.unrestorableReason}`
          }
          action={<Chip tone="info">approval required</Chip>}
        >
          {target && (
            <Facts
              rows={[
                ["Deploy version", String(target.deployVersion)],
                ["Candidate", <Mono key="c">{shortHash(target.candidateHash)}</Mono>],
                ["Image digest", <Mono key="d">{shortHash(target.imageDigest)}</Mono>],
                ["Lockfile", <Mono key="l">{shortHash(target.lockfileSha256)}</Mono>],
                ["Verified", formatWhen(target.verifiedAt)],
                ["Serves at", target.url ? <Mono key="u">{target.url}</Mono> : "not recorded"],
              ]}
            />
          )}
          {plan.dataNote && <Note className="mt-3 text-[12.5px]">{plan.dataNote}</Note>}
          {plan.providerConstraints.length > 0 && (
            <ul className="mt-2 space-y-1">
              {plan.providerConstraints.map((line) => (
                <li key={line} className="tp-den break-words">
                  {line}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>

      <StageSection id="rollback-steps">
        <Panel
          icon={<ListOrdered className="h-4 w-4 text-blue-400" />}
          label="Steps and checks"
          title="What a rollback does, in order, and what has to hold before it is called restored."
        >
          {plan.steps.length === 0 ? (
            <EmptyNote>No steps: there is no verified release to return to.</EmptyNote>
          ) : (
            <ol className="space-y-2">
              {plan.steps.map((step, index) => (
                <li key={step.id} className="flex min-w-0 gap-3">
                  <span className="tp-label mt-[3px] shrink-0">{String(index + 1).padStart(2, "0")}</span>
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 text-[13px] font-medium">
                      {step.label}
                      {step.movesTraffic && <Chip tone="caution">moves traffic</Chip>}
                    </p>
                    <p className="tp-den mt-0.5 break-words">{step.action}</p>
                    {step.constraint && <p className="tp-den break-words">{step.constraint}</p>}
                  </div>
                </li>
              ))}
            </ol>
          )}
          {plan.checks.length > 0 && (
            <>
              <p className="tp-label mt-4">Restored means</p>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {plan.checks.map((check) => (
                  <li key={check.id}>
                    <Chip title={check.expect}>
                      {check.kind} on the {check.role}
                    </Chip>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="tp-label mt-4">Per update</p>
          <ul className="mt-2 space-y-1">
            {plan.updates.map((one) => (
              <li key={one.updateId} className="flex flex-wrap items-center gap-2 text-[13px]">
                <span className="break-words">{packageOf(one.updateId)}</span>
                <Chip tone={one.status === "prepared" ? "pass" : one.status === "unavailable" ? "fail" : "neutral"}>
                  {one.status === "not-required" ? `not required at ${one.level}` : one.status}
                </Chip>
                {one.reason && <span className="tp-den">{one.reason}</span>}
              </li>
            ))}
          </ul>
        </Panel>
      </StageSection>
    </div>
  );
}
