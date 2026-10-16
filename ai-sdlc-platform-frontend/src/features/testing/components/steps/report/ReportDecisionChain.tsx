import { Workflow } from "lucide-react";
import { Panel } from "../../bits/index";
import type { DecisionChainStep } from "../../../fixtures/types";

export function ReportDecisionChain({ decisionChain }: { decisionChain: DecisionChainStep[] }) {
  return (
    <Panel
      icon={<Workflow className="h-4 w-4 text-blue-400" />}
      label="After you approve"
      title="Where an approved change goes next"
    >
      <ol className="grid gap-2 lg:grid-cols-4">
        {decisionChain.map((step, i) => (
          <li
            key={step.id}
            className="rounded-lg border border-slate-200 px-3.5 py-3 dark:border-white/[0.06]"
          >
            <p className="tp-label">
              {String(i + 1).padStart(2, "0")} · {step.label}
            </p>
            <p className="tp-prose mt-1.5 text-[12.5px]">{step.detail}</p>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
