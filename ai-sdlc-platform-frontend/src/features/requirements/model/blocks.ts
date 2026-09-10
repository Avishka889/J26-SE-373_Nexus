import type { ScreenBlock } from "../api/types";

/** A screen's blocks as they are drawn: one at a time, with consecutive keys in one grid. */
export type BlockGroup =
  | { kind: "block"; block: ScreenBlock }
  | { kind: "keys"; blocks: ScreenBlock[] };

/**
 * Consecutive buttons form a grid of keys, the way a calculator's do; every
 * other block stands on its own. Nothing is dropped or reordered.
 */
export function groupBlocks(blocks: ScreenBlock[]): BlockGroup[] {
  const groups: BlockGroup[] = [];
  for (const block of blocks) {
    const last = groups[groups.length - 1];
    if (block.kind === "button" && last?.kind === "keys") last.blocks.push(block);
    else if (block.kind === "button") groups.push({ kind: "keys", blocks: [block] });
    else groups.push({ kind: "block", block });
  }
  return groups;
}
