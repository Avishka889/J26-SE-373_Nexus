import type { UmlDiagram, UseCase } from "@sdlc/contracts-ts";

/**
 * Interaction steps are authored, because a real sequence has a request, a
 * check, a persist and a response, and none of that can be read off a single
 * actor-verb-entity triple. Names are not authored: participants are node ids
 * and message text uses `{nodeId}` tokens, so a rename in the graph propagates
 * into every line.
 */
export const seedUseCases: UseCase[] = [
  {
    id: "uc-browse",
    name: "Browse and filter the catalog",
    traces: ["R-1", "R-10"],
    storyId: "US-201",
    steps: [
      { fromId: "a1", toId: "m5", message: "opens a category", kind: "call" },
      { fromId: "m5", toId: "m1", message: "GET /products?category", kind: "call" },
      { fromId: "m1", toId: "m1", message: "read {e1} scoped to this {e5}", kind: "call" },
      { fromId: "m1", toId: "m5", message: "the matching {e1} list", kind: "return" },
      { fromId: "m5", toId: "a1", message: "shows the filtered catalog", kind: "return" },
    ],
  },
  {
    id: "uc-checkout",
    name: "Check out a cart",
    traces: ["R-3", "R-7", "R-12"],
    storyId: "US-203",
    steps: [
      { fromId: "a1", toId: "m5", message: "confirms checkout", kind: "call" },
      { fromId: "m5", toId: "m3", message: "POST /orders", kind: "call" },
      { fromId: "m3", toId: "m2", message: "what is in this {e2}", kind: "call" },
      { fromId: "m2", toId: "m3", message: "the line items", kind: "return" },
      { fromId: "m3", toId: "m4", message: "is there enough {e4} for each line", kind: "call" },
      { fromId: "m4", toId: "m3", message: "yes, every line is available", kind: "return" },
      { fromId: "m3", toId: "a4", message: "take the payment", kind: "call" },
      { fromId: "a4", toId: "m3", message: "settled", kind: "return" },
      { fromId: "m3", toId: "m3", message: "record the {e3} against this {e5}", kind: "call" },
      { fromId: "m3", toId: "m5", message: "the order number", kind: "return" },
      { fromId: "m5", toId: "a1", message: "shows the confirmation", kind: "return" },
    ],
  },
  {
    id: "uc-sync",
    name: "Sync stock from the inventory system",
    traces: ["R-4"],
    storyId: "US-206",
    steps: [
      { fromId: "a3", toId: "m4", message: "reports a new stock level", kind: "call" },
      { fromId: "m4", toId: "m4", message: "update the {e4} and stamp the sync time", kind: "call" },
      { fromId: "m4", toId: "m4", message: "the direction of a conflict is not yet decided", kind: "note" },
    ],
  },
];

export const seedDiagrams: UmlDiagram[] = [
  {
    id: "class",
    kind: "class",
    title: "Class Diagram",
    description: "The domain entities and the services that own them, generated from the graph.",
    source: null,
    useCaseId: null,
    traces: ["R-1", "R-2", "R-3"],
  },
  {
    id: "er",
    kind: "er",
    title: "Entity Relationship Diagram",
    description: "The same entities as stored data, generated from the graph.",
    source: null,
    useCaseId: null,
    traces: ["R-1", "R-3", "R-6"],
  },
  {
    id: "activity",
    kind: "activity",
    title: "Activity Diagram",
    description: "The checkout flow, including the stock check that can refuse it.",
    source: `flowchart TD
  A([Shopper confirms checkout]) --> B{Cart has line items}
  B -- no --> B1[Send them back to the catalog] --> X([Checkout not started])
  B -- yes --> C{Every line within stock}
  C -- no --> C1[Name the item and the quantity available] --> X
  C -- yes --> D[Take the payment]
  D --> E{Provider settled}
  E -- no --> F[Leave the cart untouched] --> X
  E -- yes --> G[Record the order against this storefront]
  G --> H([Order confirmed])`,
    useCaseId: null,
    traces: ["R-3", "R-7", "R-12"],
  },
  {
    id: "sequence",
    kind: "sequence",
    title: "Sequence Diagram",
    description: "One interaction per use case, with names read from the graph.",
    source: null,
    useCaseId: "uc-checkout",
    traces: ["R-3", "R-7"],
  },
];
