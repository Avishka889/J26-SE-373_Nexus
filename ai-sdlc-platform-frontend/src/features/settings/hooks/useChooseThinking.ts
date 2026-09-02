import { useMutation, useQueryClient } from "@tanstack/react-query";
import { settingsApi, type PhaseKey, type ThinkingLevel } from "@/entities/settings";
import { settingsKeys } from "@/lib/query";

/**
 * Choose how hard a phase thinks, from its next run.
 *
 * Settled only once the phases are read again, so the choice shows as saving
 * until the tab shows what the server holds.
 */
export function useChooseThinking() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ key, level }: { key: PhaseKey; level: ThinkingLevel }) =>
      settingsApi.chooseThinking(key, level),
    // Said beside the choice it belongs to, so not again by the app's toast.
    meta: { reportsOwnErrors: true },
    onSettled: () => queryClient.invalidateQueries({ queryKey: settingsKeys.models }),
  });
}
