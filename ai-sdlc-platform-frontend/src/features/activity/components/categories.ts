import type { ActivityLogCategory } from "../fixtures/activityData";

/**
 * The categories the log can be shown by, in the order the filter offers them.
 *
 * Apart from the filter's component, which exports components only so it can
 * hot reload: the page reads this list too, to open on the category its
 * address names.
 */
export const categories: { id: ActivityLogCategory | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "requirement", label: "Requirements" },
  { id: "design", label: "Design" },
  { id: "code", label: "Code" },
  { id: "testing", label: "Testing" },
  { id: "security", label: "Security" },
  { id: "deployment", label: "Deployment" },
  { id: "approval", label: "Approvals" },
];
