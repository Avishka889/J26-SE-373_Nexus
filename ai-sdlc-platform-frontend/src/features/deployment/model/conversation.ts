import type { ConversationMessage } from "@/shared/ui/conversation";
import type { DeployStageId } from "@/types/project";
import type { DeploySnapshot } from "../api/types";
import { DEPLOY_STAGE_META } from "./stages";

/**
 * This phase's transcript, from the thread the server stores.
 *
 * One conversation, oldest first, for the reason the other phases give: a
 * reader following what the platform did reads it in order. This phase's
 * thread matters more than most, because its runner stages write nothing
 * anywhere else in words: a release started, a monitoring window found the
 * release down, a rollback waits on a person. Each message opens the stage it
 * belongs to.
 */
export function buildDeploymentConversation({
  snapshot,
  onOpenStage,
}: {
  snapshot: DeploySnapshot;
  onOpenStage: (stageId: DeployStageId) => void;
}): ConversationMessage[] {
  return snapshot.thread.map((entry) => {
    const stageId = entry.stageId as DeployStageId | null;
    const stageLabel = stageId ? DEPLOY_STAGE_META[stageId].label : undefined;
    const opens = stageId
      ? { onOpen: () => onOpenStage(stageId), openLabel: `Open ${stageLabel}` }
      : {};

    if (entry.kind === "stage_summary" && stageId) {
      return {
        id: entry.id,
        role: "agent" as const,
        author: entry.author,
        content: entry.content,
        at: entry.at,
        chip: stageLabel,
        ...opens,
      };
    }

    // A system message written in a person's name is their decision, recorded;
    // one written by the platform is what the platform did.
    const byPerson = entry.kind === "user_note" || entry.author !== "platform";
    return {
      id: entry.id,
      role: byPerson ? ("user" as const) : ("system" as const),
      author: entry.author,
      content: entry.content,
      at: entry.at,
      chip: stageLabel,
      ...opens,
    };
  });
}
