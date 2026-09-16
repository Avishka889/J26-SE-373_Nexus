import type { ManifestRow } from "../api/types";
import { ARM_NAMES } from "./arms";

/**
 * A file's facts from the manifest, as tags on its row in the file tree.
 *
 * Who wrote it and from which arm, and, for a page an earlier generation made,
 * that it was kept unchanged: nothing it depends on had changed, so it was not
 * rewritten, and a reviewer who read it at that version need not read it again.
 * Then each applied security fix carried into it when the code was generated
 * again, named by the version the fix was applied as.
 */
export function fileTags(row: ManifestRow): string[] {
  return [
    row.generator,
    ARM_NAMES[row.arm] ?? row.arm,
    ...(row.reusedFromVersion > 0 ? [`unchanged since v${row.reusedFromVersion}`] : []),
    ...row.carriedFixes.map((version) => `security fix from v${version}`),
  ];
}
