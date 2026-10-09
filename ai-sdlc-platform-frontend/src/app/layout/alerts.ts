import type { AttentionItem } from "@/entities/attention";

/** One line in the bell's panel. */
export interface Alert {
  id: string;
  severity: "warning" | "info";
  title: string;
  message: string;
  /** The page where it is decided. */
  href?: string;
}

/** Each phase's page. */
const PHASE_PATH: Record<AttentionItem["phase"], string> = {
  design: "requirements",
  code: "code",
  testing: "testing",
  deployment: "deployment",
};

/**
 * What the bell shows in the running app: what the server says waits on the
 * signed-in person, each line opening the page where it is decided. It said
 * "Nothing needs you right now" while thirty seven reviews waited.
 */
export function alertsFromAttention(items: AttentionItem[]): Alert[] {
  return items.map((item) => ({
    id: item.id,
    // A review is a decision someone is waiting for; a rollback or a run that
    // stopped is something that went wrong.
    severity: item.kind === "review" ? "info" : "warning",
    title: item.title,
    message: item.projectName ? `${item.projectName}: ${item.message}` : item.message,
    href: `/projects/${item.projectId}/${PHASE_PATH[item.phase]}`,
  }));
}

/**
 * What the bell shows on fixtures.
 *
 * The two lines are made up: that the first project has a design review
 * pending, whether or not one is, and that a model is configured from a tab
 * nothing on the backend reads. They stay for a run on fixtures, where the
 * whole product is demo data and says so; the running app reads
 * `alertsFromAttention` instead.
 */
export function alertsFor(
  allFixtures: boolean,
  firstProject: string | undefined,
  model: string,
): Alert[] {
  if (!allFixtures) return [];
  return [
    {
      id: "1",
      severity: "warning",
      title: "Approval needed",
      message: firstProject
        ? `${firstProject} has a pending design review`
        : "Connect integrations in Settings",
    },
    {
      id: "2",
      severity: "info",
      title: "AI model ready",
      message: `${model} is configured for generation`,
    },
  ];
}
