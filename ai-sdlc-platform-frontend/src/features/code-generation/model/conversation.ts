import type { ConversationMessage } from "@/shared/ui/conversation";
import type { CodeStageId } from "@/types/project";
import type { CodeSnapshot } from "../api/types";
import { CODE_STAGE_META } from "./stages";

/**
 * The code phase's transcript, from the thread the server stores.
 *
 * One conversation rather than a log per stage: a reader following what the
 * platform did reads it in order, and every stage summary opens the stage it
 * describes. A message that produced a new code version says so, because "why
 * is this at version 3" is the question a transcript exists to answer.
 */
export function buildCodeConversation({
  snapshot,
  onOpenStage,
}: {
  snapshot: CodeSnapshot;
  onOpenStage: (stageId: CodeStageId) => void;
}): ConversationMessage[] {
  return snapshot.thread.map((entry) => {
    const stageId = entry.stageId as CodeStageId | null;
    const stageLabel = stageId ? CODE_STAGE_META[stageId].label : undefined;
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
