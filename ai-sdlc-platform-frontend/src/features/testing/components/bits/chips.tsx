import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  Circle,
  CircleDot,
  Clock,
  Bug,
  Minus,
  PauseCircle,
  ShieldAlert,
  Wrench,
  X,
} from "lucide-react";
import { Badge } from "@/shared/ui/primitives";
import type { FindingStatus, ProofState, Severity } from "../../fixtures/types";
import type { ViewFailure } from "../../model/view";
import { severityLabel } from "./chipLabels";
import { Spinner } from "@/shared/ui/Spinner";

const severityIcon: Record<Severity, typeof ShieldAlert> = {
  critical: ShieldAlert,
  high: AlertTriangle,
  medium: AlertCircle,
  low: Minus,
  none: Minus,
};

/** red → orange → amber → slate, using the Badge variants the app already has. */
const severityVariant: Record<Severity, "error" | "c4" | "warning" | "default"> = {
  critical: "error",
  high: "c4",
  medium: "warning",
  low: "default",
  none: "default",
};

export function SeverityChip({ severity }: { severity: Severity }) {
  const Icon = severityIcon[severity];
  return (
    <Badge variant={severityVariant[severity]}>
      <Icon className="h-3 w-3" />
      {severityLabel[severity]}
    </Badge>
  );
}

export function FindingStatusChip({ status }: { status: FindingStatus }) {
  if (status === "verified")
    return (
      <Badge variant="success">
        <CheckCircle2 className="h-3 w-3" />
        Fixed and re-verified
      </Badge>
    );
  if (status === "re-verifying")
    return (
      <Badge variant="warning">
        <Spinner size="xs" decorative />
        Re-verifying
      </Badge>
    );
  if (status === "fix-applied")
    return (
      <Badge variant="warning">
        <Wrench className="h-3 w-3" />
        Fix applied
      </Badge>
    );
  if (status === "fix-proposed")
    return (
      <Badge variant="default">
        <Wrench className="h-3 w-3" />
        Fix proposed
      </Badge>
    );
  if (status === "dismissed")
    return (
      <Badge variant="default">
        <X className="h-3 w-3" />
        Dismissed
      </Badge>
    );
  return (
    <Badge variant="default">
      <CircleDot className="h-3 w-3" />
      Open
    </Badge>
  );
}

export function TriageChip({ failure }: { failure: ViewFailure }) {
  if (failure.awaitingRerun)
    return (
      <Badge variant="info" title="Counted as passing from the guard run. The next full run records it.">
        <Check className="h-3 w-3" />
        Approved · awaiting re-run
      </Badge>
    );
  if (failure.triage === "healed" || failure.state === "healed")
    return (
      <Badge variant="success">
        <Check className="h-3 w-3" />
        Healed
      </Badge>
    );
  if (failure.triage === "regression")
    return (
      <Badge variant="error">
        <Bug className="h-3 w-3" />
        Real regression
      </Badge>
    );
  if (failure.triage === "unclassified")
    return (
      <Badge variant="default" title="Nothing has said yet whether the test or the code is wrong.">
        <Circle className="h-3 w-3" />
        Not classified
      </Badge>
    );
  return (
    <Badge variant="warning">
      <Wrench className="h-3 w-3" />
      Brittle test
    </Badge>
  );
}

export function StateChip({ failure }: { failure: ViewFailure }) {
  if (failure.state === "quarantined")
    return (
      <Badge variant="warning" title="Skipped, with its reason in the test file, until restored.">
        <PauseCircle className="h-3 w-3" />
        Quarantined
      </Badge>
    );
  if (failure.state === "awaiting-approval")
    return (
      <Badge variant="info">
        <Clock className="h-3 w-3" />
        Awaiting you
      </Badge>
    );
  if (failure.state === "blocked")
    return (
      <Badge variant="error">
        <ShieldAlert className="h-3 w-3" />
        Guard rejected the repair
      </Badge>
    );
  // "With the developer" named a hand-off that never happened: nothing assigns
  // a live failure to anyone, so the badge says what the failure needs.
  if (failure.state === "escalated")
    return (
      <Badge variant="default">
        <Circle className="h-3 w-3" />
        {failure.owner
          ? `With ${failure.owner}`
          : failure.triage === "regression"
            ? "Needs a code change"
            : "Needs a person"}
      </Badge>
    );
  return null;
}

export function ProofChip({ state }: { state: ProofState }) {
  if (state === "errored")
    return (
      <Badge variant="warning">
        <AlertTriangle className="h-3 w-3" />
        Could not run
      </Badge>
    );
  if (state === "pass")
    return (
      <Badge variant="success">
        <Check className="h-3 w-3" />
        Passed
      </Badge>
    );
  if (state === "fail")
    return (
      <Badge variant="error">
        <X className="h-3 w-3" />
        Failed
      </Badge>
    );
  if (state === "running")
    return (
      <Badge variant="warning">
        <Spinner size="xs" decorative />
        Running
      </Badge>
    );
  return (
    <Badge variant="default">
      <Clock className="h-3 w-3" />
      Queued
    </Badge>
  );
}

