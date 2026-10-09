import { beforeEach, describe, expect, it } from "vitest";
import { useUiStore } from "./ui";

/**
 * The phone sheet must start closed on every visit.
 *
 * The sheet used to render off the persisted desk preference, so a reader who
 * kept the desktop column open got a full screen sheet covering the work on
 * first paint at phone width. The sheet state is therefore separate and never
 * written to storage.
 */
describe("the conversation sheet state", () => {
  beforeEach(() => {
    localStorage.clear();
    useUiStore.setState({ conversationOpen: true, conversationSheetOpen: false });
  });

  it("starts closed even though the desk column starts open", () => {
    const state = useUiStore.getState();
    expect(state.conversationOpen).toBe(true);
    expect(state.conversationSheetOpen).toBe(false);
  });

  it("opens and closes through its own setter", () => {
    useUiStore.getState().setConversationSheetOpen(true);
    expect(useUiStore.getState().conversationSheetOpen).toBe(true);
    useUiStore.getState().setConversationSheetOpen(false);
    expect(useUiStore.getState().conversationSheetOpen).toBe(false);
  });

  it("is never persisted, while the desk preference is", () => {
    // Writing any persisted field flushes the partialized state to storage.
    useUiStore.getState().setConversationSheetOpen(true);
    useUiStore.getState().setConversationOpen(false);

    const written = JSON.parse(localStorage.getItem("nexus-ui") ?? "{}");
    expect(written.state).toBeDefined();
    expect(written.state.conversationOpen).toBe(false);
    // The sheet key must be absent, not merely false: a persisted true would
    // reopen the sheet over the work on the next visit.
    expect("conversationSheetOpen" in written.state).toBe(false);
  });
});
