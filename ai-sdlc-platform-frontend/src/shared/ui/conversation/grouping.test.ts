import { describe, expect, it } from "vitest";
import { grouped } from "./grouping";
import type { ConversationMessage } from "./types";

const record = (id: string, extra: Partial<ConversationMessage> = {}): ConversationMessage => ({
  id,
  role: "system",
  author: "platform",
  content: `record ${id}`,
  at: "12:00",
  ...extra,
});
const said = (id: string): ConversationMessage => ({ ...record(id), role: "user", author: "You" });

describe("the transcript's folds", () => {
  it("folds three or more records in a row into one item, in order", () => {
    const items = grouped([said("a"), record("1"), record("2"), record("3"), said("b")]);

    expect(items.map((item) => item.kind)).toEqual(["message", "events", "message"]);
    expect(items[1].kind === "events" && items[1].events.map((one) => one.id)).toEqual([
      "1",
      "2",
      "3",
    ]);
  });

  it("leaves two records in a row as lines", () => {
    const items = grouped([record("1"), record("2"), said("a")]);

    expect(items.map((item) => item.kind)).toEqual(["message", "message", "message"]);
  });

  it("never folds a record that can be opened or answered", () => {
    const opens = record("2", { onOpen: () => undefined, openLabel: "Open it" });
    const items = grouped([record("1"), opens, record("3")]);

    expect(items.every((item) => item.kind === "message")).toBe(true);
  });

  it("drops nothing", () => {
    const messages = [record("1"), record("2"), record("3"), said("a"), record("4")];
    const items = grouped(messages);
    const shown = items.flatMap((item) => (item.kind === "events" ? item.events : [item.message]));

    expect(shown.map((one) => one.id)).toEqual(messages.map((one) => one.id));
  });
});
