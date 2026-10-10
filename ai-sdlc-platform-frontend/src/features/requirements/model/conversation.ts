import type { DesignStageId } from "@/types/project";
import type { ConversationMessage } from "@/shared/ui/conversation";
import type { DesignSnapshot } from "../api/types";
import { STAGE_META } from "./stages";

/**
 * The design snapshot as a conversation.
 *
 * Every entry is a real event that already exists in the artifact: the input the
 * reader wrote, the summaries the agent posted, the questions it is waiting on,
 * the answers given, the changes requested and the decision taken. Nothing is
 * invented to fill the panel out, because a transcript with invented turns in it
 * stops being evidence of what happened.
 *
 * The requirements list itself deliberately stays in the stage. A transcript is a
 * log; an editable, filterable artifact is state, and state embedded in a log
 * goes stale the moment a regeneration appends a newer copy above it. What the
 * chat carries is the summary that links to it.
 */
export function buildConversation({
  snapshot,
  onOpenStage,
  onAnswerQuestion,
  answering,
}: {
  snapshot: DesignSnapshot;
  onOpenStage: (stageId: DesignStageId) => void;
  onAnswerQuestion: (questionId: string, answer: string) => void | Promise<unknown>;
  answering: boolean;
}): ConversationMessage[] {
  const messages = snapshot.thread.flatMap((entry): ConversationMessage[] => {
    const stageLabel = entry.stageId ? STAGE_META[entry.stageId].label : undefined;

    if (entry.kind === "stage_summary" && entry.stageId) {
      const stageId = entry.stageId;
      return [
        {
          id: entry.id,
          role: "agent",
          author: entry.author,
          content: entry.content,
          at: entry.at,
          chip: stageLabel,
          onOpen: () => onOpenStage(stageId),
          openLabel: `Open ${STAGE_META[stageId].label}`,
        },
      ];
    }

    if (entry.kind === "user_note" || entry.kind === "answer") {
      const said: ConversationMessage = {
        id: entry.id,
        role: "user",
        author: entry.author,
        content: entry.content,
        at: entry.at,
        // The version chip goes on the message that opened it, taken from the
        // record rather than counted down the transcript.
        chip: entry.producedVersion ? `Version ${entry.producedVersion}` : stageLabel,
        // The first thing said is the requirement input, and a pasted document
        // would otherwise be the only thing on screen.
        collapsible: true,
      };
      // An answered question is no longer open, so it is drawn here, above its
      // answer, as it was asked: the answer's words alone said nothing of what
      // they answered. The server pairs it, from the version it was asked in.
      const asked = entry.kind === "answer" ? entry.question : null;
      if (!asked) return [said];
      return [
        {
          id: `asked-${entry.id}`,
          role: "agent",
          author: "Design agent",
          content: asked.question,
          at: asked.askedAt,
          chip: asked.traces.join(", "),
        },
        said,
      ];
    }

    return [
      {
        id: entry.id,
        role: "system",
        author: entry.author,
        content: entry.content,
        at: entry.at,
        chip: stageLabel,
      },
    ];
  });

  // Open questions come from the artifact rather than the thread, so answering
  // one clears it here and in the stage and in the review at the same moment:
  // there is one record of whether it has been answered.
  for (const question of snapshot.questions) {
    if (question.answer) continue;
    messages.push({
      id: `q-${question.id}`,
      role: "agent",
      author: "Design agent",
      content: question.question,
      at: snapshot.stages.requirements.generatedAt ?? "",
      chip: question.traces.join(", "),
      answer: {
        placeholder: "Answer in a sentence",
        pending: answering,
        onSubmit: (text) => onAnswerQuestion(question.id, text),
      },
    });
  }

  return messages;
}
