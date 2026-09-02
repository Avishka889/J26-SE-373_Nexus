import { useQuery } from "@tanstack/react-query";
import { attentionKeys } from "@/lib/query";
import { attentionApi, type AttentionItem } from "./api";

/** How often the bell asks again, besides whenever the window regains focus. */
const ASK_EVERY_MS = 30_000;

/**
 * What waits on the signed-in person: reviews, rollbacks, and runs that
 * stopped. Asked only where the server is the source, never of fixtures.
 */
export function useAttention(enabled: boolean): AttentionItem[] {
  const query = useQuery({
    queryKey: attentionKeys.all,
    queryFn: attentionApi.list,
    enabled,
    refetchInterval: enabled ? ASK_EVERY_MS : false,
  });
  return query.data ?? [];
}
