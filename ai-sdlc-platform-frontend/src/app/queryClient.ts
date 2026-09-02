import { createQueryClient } from "@/lib/query";
import { messageOf } from "@/lib/http";
import { useUiStore } from "@/store/ui";

/**
 * The app's one query client.
 *
 * A module of its own so that what is not a component, signing out among
 * them, can reach it without a provider around it.
 */
export const queryClient = createQueryClient({
  onMutationError: (error) =>
    useUiStore.getState().addToast({
      type: "error",
      title: "That did not go through",
      message: messageOf(error),
    }),
});
