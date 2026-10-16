import type { ConversationMessage } from "@/shared/ui/conversation";
import type { TestStageId } from "@/types/project";
import type { TestSnapshot } from "../api/types";
import { TEST_STAGE_META } from "./stages";

/**
 * This phase's transcript, from the thread the server stores.
 *
 * One conversation rather than a log per stage, for the reason the other two
 * phases give: a reader following what the platform did reads it in order, and
 * every stage summary opens the stage it describes.
 *
 * This phase had no conversation at all until now, which mattered more here
 * than the missing panel suggests. Its refusals arrive as thread messages: when
 * C3 will not subtract two passes that were not measured alike, the reason is
 * written to the thread and nothing is stored, so a phase with no transcript
 * had nowhere to put the one sentence explaining why a re-verification produced
 * no answer. It was recorded and unreadable.
 */
export function buildTestingConversation({
  snapshot,
  onOpenStage,
}: {
  snapshot: TestSnapshot;
  onOpenStage: (stageId: TestStageId) => void;
}): ConversationMessage[] {
  return snapshot.thread.map((entry) => {
    const stageId = entry.stageId as TestStageId | null;
    const stageLabel = stageId ? TEST_STAGE_META[stageId].label : undefined;
    const version = entry.producedVersion ? ` · produced v${entry.producedVersion}` : "";

    if (entry.kind === "stage_summary" && stageId) {
      return {
        id: entry.id,
        role: "agent" as const,
        author: entry.author,
        content: entry.content,
        at: entry.at,
        chip: stageLabel,
        onOpen: () => onOpenStage(stageId),
        openLabel: `Open ${stageLabel}`,
      };
    }

    return {
      id: entry.id,
      role: entry.kind === "system" ? ("system" as const) : ("user" as const),
      author: entry.author,
      content: entry.content,
      at: entry.at,
      chip: stageLabel ? `${stageLabel}${version}` : version.trim() || undefined,
      ...(stageId
        ? { onOpen: () => onOpenStage(stageId), openLabel: `Open ${stageLabel}` }
        : {}),
    };
  });
}
