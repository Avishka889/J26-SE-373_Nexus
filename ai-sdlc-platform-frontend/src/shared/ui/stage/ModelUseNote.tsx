import type { StageModelUse } from "@sdlc/contracts-ts";
import { thinkingWords, tokenCount } from "@/shared/utils/modelWords";

/**
 * Which model answered a stage, and what that took, under the stage itself.
 *
 * The model is the one the responses named, which is what the provider says
 * answered rather than the name the platform was configured with: DeepSeek
 * serves some names with another model, and only the response can show it.
 * Requests count every answer, so a stage that had to ask again says so.
 */
export function ModelUseNote({ use }: { use: StageModelUse }) {
  const thinking = use.thinking.length > 0 ? `, ${use.thinking.map(thinkingWords).join(" and ")}` : "";
  const reasoning =
    use.reasoningTokens > 0 ? `, ${tokenCount(use.reasoningTokens)} of them reasoning` : "";
  return (
    <p className="tp-den break-words text-[12px]" data-model-use>
      Answered by {use.answeredBy.join(" and ")}
      {thinking}: {use.requests} request{use.requests === 1 ? "" : "s"},{" "}
      {tokenCount(use.tokensIn)} tokens in and {tokenCount(use.tokensOut)} out{reasoning}.
    </p>
  );
}
