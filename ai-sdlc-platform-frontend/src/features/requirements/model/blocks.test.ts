import { describe, expect, it } from "vitest";
import type { ScreenBlock } from "../api/types";
import { groupBlocks } from "./blocks";

const block = (id: string, kind: ScreenBlock["kind"]): ScreenBlock =>
  ({ id, kind, label: id, value: null, tone: null, linkId: null }) as ScreenBlock;

describe("a screen's blocks as drawn", () => {
  it("puts consecutive buttons in one grid of keys, and leaves the rest alone", () => {
    const groups = groupBlocks([
      block("d", "display"),
      block("k1", "button"),
      block("k2", "button"),
      block("t", "text"),
      block("k3", "button"),
    ]);

    expect(groups.map((group) => group.kind)).toEqual(["block", "keys", "block", "keys"]);
    expect(groups[1].kind === "keys" && groups[1].blocks.map((one) => one.id)).toEqual(["k1", "k2"]);
  });

  it("drops and reorders nothing", () => {
    const blocks = [block("a", "field"), block("b", "button"), block("c", "display")];
    const drawn = groupBlocks(blocks).flatMap((group) =>
      group.kind === "keys" ? group.blocks : [group.block],
    );

    expect(drawn.map((one) => one.id)).toEqual(["a", "b", "c"]);
  });
});
