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
    id: "uc-pay",
    name: "Pay with a saved card",
    traces: ["R-1", "R-2", "R-10", "R-11"],
    storyId: "US-101",
    steps: [
      { fromId: "a1", toId: "m6", message: "chooses a saved card and confirms", kind: "call" },
      { fromId: "m6", toId: "m5", message: "POST /payments", kind: "call" },
      { fromId: "m5", toId: "m1", message: "is this {e6} still valid", kind: "call" },
      { fromId: "m1", toId: "m5", message: "yes, {e6} is valid", kind: "return" },
      { fromId: "m5", toId: "m2", message: "create a {e2}", kind: "call" },
      { fromId: "m2", toId: "m3", message: "does this {a1} need a {e3}", kind: "call" },
      { fromId: "m3", toId: "m2", message: "below the threshold, no {e3} needed", kind: "return" },
      { fromId: "m2", toId: "a3", message: "charge the card", kind: "call" },
      { fromId: "a3", toId: "m2", message: "settled", kind: "return" },
      { fromId: "m2", toId: "m2", message: "record the {e2} and append an {e5}", kind: "call" },
      { fromId: "m2", toId: "m4", message: "tell the {a1} it worked", kind: "call" },
      { fromId: "m2", toId: "m6", message: "confirmed", kind: "return" },
      { fromId: "m6", toId: "a1", message: "shows the confirmation", kind: "return" },
    ],
  },
  {
    id: "uc-verify",
    name: "Verify identity before a large payment",
    traces: ["R-3", "R-4"],
    storyId: "US-103",
    steps: [
      { fromId: "a1", toId: "m6", message: "starts a payment above the threshold", kind: "call" },
      { fromId: "m6", toId: "m5", message: "POST /payments", kind: "call" },
      { fromId: "m5", toId: "m2", message: "create a {e2}", kind: "call" },
      { fromId: "m2", toId: "m3", message: "does this {a1} need a {e3}", kind: "call" },
      { fromId: "m3", toId: "m2", message: "yes, above the threshold", kind: "return" },
      { fromId: "m2", toId: "m6", message: "hold the {e2} and ask for documents", kind: "return" },
      { fromId: "a1", toId: "m3", message: "submits a document", kind: "call" },
      { fromId: "m3", toId: "a4", message: "check this document", kind: "call" },
      { fromId: "a4", toId: "m3", message: "looks genuine", kind: "return" },
      { fromId: "a2", toId: "m3", message: "approves the {e3}", kind: "call" },
      { fromId: "m3", toId: "m2", message: "{e3} approved, release the {e2}", kind: "call" },
      { fromId: "m2", toId: "m4", message: "tell the {a1} it went through", kind: "call" },
    ],
  },
  {
    id: "uc-review",
    name: "Review submitted documents",
    traces: ["R-4", "R-5"],
    storyId: "US-104",
    steps: [
      { fromId: "a2", toId: "m6", message: "opens the review queue", kind: "call" },
      { fromId: "m6", toId: "m5", message: "GET /verifications?status=pending", kind: "call" },
      { fromId: "m5", toId: "m3", message: "list the waiting records", kind: "call" },
      { fromId: "m3", toId: "m5", message: "the pending {e3} records", kind: "return" },
      { fromId: "a2", toId: "m3", message: "approves or rejects one", kind: "call" },
      { fromId: "m3", toId: "m3", message: "append an {e5} naming the reviewer", kind: "call" },
      { fromId: "m3", toId: "m4", message: "tell the {a1} the outcome", kind: "call" },
    ],
  },
];

/**
 * Class and entity relationship diagrams carry no source: they are generated
 * from the graph projection, so they cannot drift from it. Activity is authored
 * because it describes a decision flow the graph does not encode.
 */
export const seedDiagrams: UmlDiagram[] = [
  {
    id: "class",
    kind: "class",
    title: "Class Diagram",
    description: "The domain entities and the services that own them, generated from the graph.",
    source: null,
    useCaseId: null,
    traces: ["R-1", "R-3", "R-5"],
  },
  {
    id: "er",
    kind: "er",
    title: "Entity Relationship Diagram",
    description: "The same entities as stored data, generated from the graph.",
    source: null,
    useCaseId: null,
    traces: ["R-1", "R-5", "R-9"],
  },
  {
    id: "activity",
    kind: "activity",
    title: "Activity Diagram",
    description: "The checkout decision flow, including the verification branch.",
    source: `flowchart TD
  A([Customer confirms payment]) --> B{Session valid}
  B -- no --> B1[Ask the customer to sign in] --> B
  B -- yes --> C{Amount above the threshold}
  C -- no --> E[Charge the card]
  C -- yes --> D{Identity already verified}
  D -- no --> D1[Ask for a document] --> D2[Administrator reviews it]
  D2 --> D3{Approved}
  D3 -- no --> X([Payment refused])
  D3 -- yes --> E
  D -- yes --> E
  E --> F{Provider settled}
  F -- no --> X
  F -- yes --> G[Record the payment and append an audit entry]
  G --> H[Notify the customer]
  H --> I([Payment confirmed])`,
    useCaseId: null,
    traces: ["R-1", "R-3", "R-5", "R-6"],
  },
  {
    id: "sequence",
    kind: "sequence",
    title: "Sequence Diagram",
    description: "One interaction per use case, with names read from the graph.",
    source: null,
    useCaseId: "uc-pay",
    traces: ["R-1", "R-2", "R-11"],
  },
];
