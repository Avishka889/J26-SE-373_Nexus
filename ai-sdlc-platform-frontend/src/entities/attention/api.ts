import { http } from "@/lib/http";

/** One thing waiting on the signed-in person, as the server lists it. */
export interface AttentionItem {
  id: string;
  kind: "review" | "rollback" | "stopped";
  projectId: string;
  projectName: string;
  phase: "design" | "code" | "testing" | "deployment";
  title: string;
  message: string;
  /** When it started waiting; none for a run that stopped. */
  at: string | null;
}

export const attentionApi = {
  list: () => http.get<AttentionItem[]>("/attention"),
};
