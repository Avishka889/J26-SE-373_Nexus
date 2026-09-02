import type { WireframeFlow } from "@sdlc/contracts-ts";

/**
 * Screens are declarative blocks rather than hand written markup, which is what
 * lets a card render a real miniature of the screen instead of an empty
 * placeholder. Every card here has authored screens: nothing falls through to a
 * generated stand-in.
 *
 * Breadcrumbs deliberately omit the product name. The player prefixes the
 * project's own name from state, so the fixture cannot hard code a brand.
 */
export const seedWireframes: WireframeFlow[] = [
  {
    id: "flow-sign-in",
    name: "Sign in",
    version: "v1",
    traces: ["R-11"],
    coversStoryIds: ["US-101"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "sign-in",
        name: "Sign in",
        terminal: false,
        crumbs: ["Sign in"],
        blocks: [
          { id: "b1", kind: "text", label: "Sign in to continue", value: null, tone: "neutral", linkId: null },
          { id: "b2", kind: "field", label: "Email", value: "you@example.com", tone: "muted", linkId: null },
          { id: "b3", kind: "field", label: "Password", value: "________", tone: "muted", linkId: null },
        ],
        links: [
          { id: "l1", label: "Sign in", targetId: "overview", variant: "primary" },
          { id: "l2", label: "Forgot password", targetId: "sign-in", variant: "text" },
        ],
      },
      {
        id: "overview",
        name: "Overview",
        terminal: false,
        crumbs: ["Overview"],
        blocks: [
          { id: "b1", kind: "summary", label: "Balance", value: "1,240.00", tone: "neutral", linkId: null },
          { id: "b2", kind: "row", label: "Make a payment", value: null, tone: "neutral", linkId: "l1" },
          { id: "b3", kind: "row", label: "Transaction history", value: null, tone: "neutral", linkId: "l2" },
        ],
        links: [
          { id: "l1", label: "Make a payment", targetId: "overview", variant: "row" },
          { id: "l2", label: "Transaction history", targetId: "overview", variant: "row" },
        ],
      },
    ],
  },
  {
    id: "flow-overview",
    name: "Overview",
    version: "v1",
    traces: ["R-7"],
    coversStoryIds: ["US-106"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "overview",
        name: "Overview",
        terminal: false,
        crumbs: ["Overview"],
        blocks: [
          { id: "b1", kind: "summary", label: "Balance", value: "1,240.00", tone: "neutral", linkId: null },
          { id: "b2", kind: "text", label: "Recent activity", value: null, tone: "muted", linkId: null },
          { id: "b3", kind: "row", label: "Coffee subscription", value: "12.00", tone: "neutral", linkId: "l1" },
          { id: "b4", kind: "row", label: "Book store", value: "38.50", tone: "neutral", linkId: "l1" },
          { id: "b5", kind: "row", label: "Train ticket", value: "94.20", tone: "neutral", linkId: "l1" },
        ],
        links: [
          { id: "l1", label: "Open a payment", targetId: "history", variant: "row" },
          { id: "l2", label: "See all", targetId: "history", variant: "secondary" },
        ],
      },
      {
        id: "history",
        name: "Transaction history",
        terminal: false,
        crumbs: ["Overview", "History"],
        blocks: [
          { id: "b1", kind: "text", label: "Newest first", value: null, tone: "muted", linkId: null },
          { id: "b2", kind: "row", label: "Coffee subscription", value: "Settled", tone: "positive", linkId: null },
          { id: "b3", kind: "row", label: "Book store", value: "Settled", tone: "positive", linkId: null },
          { id: "b4", kind: "row", label: "Train ticket", value: "Refused", tone: "muted", linkId: null },
          { id: "b5", kind: "row", label: "Gift card", value: "Settled", tone: "positive", linkId: null },
        ],
        links: [{ id: "l1", label: "Back to overview", targetId: "overview", variant: "secondary" }],
      },
    ],
  },
  {
    id: "flow-payment",
    name: "Payment",
    version: "updated after review",
    traces: ["R-1", "R-2", "R-10"],
    coversStoryIds: ["US-101", "US-102"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "amount",
        name: "Amount",
        terminal: false,
        crumbs: ["Pay", "Amount"],
        blocks: [
          { id: "b1", kind: "field", label: "Pay to", value: "Book store", tone: "neutral", linkId: null },
          { id: "b2", kind: "field", label: "Amount", value: "38.50", tone: "neutral", linkId: null },
        ],
        links: [{ id: "l1", label: "Continue", targetId: "method", variant: "primary" }],
      },
      {
        id: "method",
        name: "Payment method",
        terminal: false,
        crumbs: ["Pay", "Method"],
        blocks: [
          { id: "b1", kind: "row", label: "Saved card ending 4242", value: null, tone: "neutral", linkId: "l1" },
          { id: "b2", kind: "row", label: "Digital wallet", value: null, tone: "neutral", linkId: "l1" },
          { id: "b3", kind: "text", label: "Card details never reach this platform", value: null, tone: "muted", linkId: null },
        ],
        links: [
          { id: "l1", label: "Use this method", targetId: "confirm", variant: "row" },
          { id: "l2", label: "Back", targetId: "amount", variant: "secondary" },
        ],
      },
      {
        id: "confirm",
        name: "Confirm",
        terminal: false,
        crumbs: ["Pay", "Confirm"],
        blocks: [
          { id: "b1", kind: "summary", label: "Total", value: "38.50", tone: "neutral", linkId: null },
          { id: "b2", kind: "field", label: "Paying with", value: "Card ending 4242", tone: "muted", linkId: null },
        ],
        links: [
          { id: "l1", label: "Confirm payment", targetId: "done", variant: "primary" },
          { id: "l2", label: "Change method", targetId: "method", variant: "secondary" },
        ],
      },
      {
        id: "done",
        name: "Confirmation",
        terminal: true,
        crumbs: ["Pay", "Done"],
        blocks: [
          { id: "b1", kind: "banner", label: "Payment confirmed", value: null, tone: "positive", linkId: null },
          { id: "b2", kind: "summary", label: "Paid", value: "38.50", tone: "neutral", linkId: null },
          { id: "b3", kind: "field", label: "Reference", value: "PY-4821", tone: "muted", linkId: null },
        ],
        links: [{ id: "l1", label: "Back to overview", targetId: "amount", variant: "secondary" }],
      },
    ],
  },
  {
    id: "flow-verification",
    name: "Identity check",
    version: "v1",
    traces: ["R-3"],
    coversStoryIds: ["US-103"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "prompt",
        name: "Verification needed",
        terminal: false,
        crumbs: ["Pay", "Verify"],
        blocks: [
          { id: "b1", kind: "banner", label: "This payment needs identity verification", value: null, tone: "neutral", linkId: null },
          { id: "b2", kind: "text", label: "Payments above the threshold are checked once, not every time.", value: null, tone: "muted", linkId: null },
        ],
        links: [{ id: "l1", label: "Upload a document", targetId: "upload", variant: "primary" }],
      },
      {
        id: "upload",
        name: "Upload document",
        terminal: false,
        crumbs: ["Pay", "Verify", "Upload"],
        blocks: [
          { id: "b1", kind: "field", label: "Document type", value: "Passport", tone: "neutral", linkId: null },
          { id: "b2", kind: "field", label: "File", value: "passport.jpg", tone: "muted", linkId: null },
        ],
        links: [
          { id: "l1", label: "Submit for review", targetId: "waiting", variant: "primary" },
          { id: "l2", label: "Back", targetId: "prompt", variant: "secondary" },
        ],
      },
      {
        id: "waiting",
        name: "Waiting for review",
        terminal: false,
        crumbs: ["Pay", "Verify", "Waiting"],
        blocks: [
          { id: "b1", kind: "banner", label: "Submitted, waiting for review", value: null, tone: "neutral", linkId: null },
          { id: "b2", kind: "text", label: "Your payment is held until this is approved.", value: null, tone: "muted", linkId: null },
        ],
        links: [{ id: "l1", label: "Back to overview", targetId: "prompt", variant: "secondary" }],
      },
    ],
  },
  {
    id: "flow-review-queue",
    name: "Review queue",
    version: "v1",
    traces: ["R-4", "R-5"],
    coversStoryIds: ["US-104"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "queue",
        name: "Review queue",
        terminal: false,
        crumbs: ["Admin", "Queue"],
        blocks: [
          { id: "b1", kind: "text", label: "3 waiting", value: null, tone: "muted", linkId: null },
          { id: "b2", kind: "row", label: "Passport, submitted today", value: null, tone: "neutral", linkId: "l1" },
          { id: "b3", kind: "row", label: "Driving licence, submitted today", value: null, tone: "neutral", linkId: "l1" },
          { id: "b4", kind: "row", label: "Passport, submitted yesterday", value: null, tone: "neutral", linkId: "l1" },
        ],
        links: [{ id: "l1", label: "Open", targetId: "review", variant: "row" }],
      },
      {
        id: "review",
        name: "Review document",
        terminal: false,
        crumbs: ["Admin", "Queue", "Review"],
        blocks: [
          { id: "b1", kind: "field", label: "Customer", value: "A. Chen", tone: "neutral", linkId: null },
          { id: "b2", kind: "field", label: "Document", value: "Passport", tone: "neutral", linkId: null },
          { id: "b3", kind: "text", label: "Approving releases the held payment.", value: null, tone: "muted", linkId: null },
        ],
        links: [
          { id: "l1", label: "Approve", targetId: "queue", variant: "primary" },
          { id: "l2", label: "Reject", targetId: "queue", variant: "secondary" },
        ],
      },
    ],
  },
  {
    id: "flow-audit",
    name: "Audit trail",
    version: "v1",
    traces: ["R-5"],
    coversStoryIds: ["US-107"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "audit",
        name: "Audit trail",
        terminal: false,
        crumbs: ["Admin", "Audit"],
        blocks: [
          { id: "b1", kind: "text", label: "Read only, newest first", value: null, tone: "muted", linkId: null },
          { id: "b2", kind: "row", label: "Payment recorded", value: "09:41", tone: "neutral", linkId: null },
          { id: "b3", kind: "row", label: "Verification approved", value: "09:38", tone: "neutral", linkId: null },
          { id: "b4", kind: "row", label: "Document submitted", value: "09:22", tone: "neutral", linkId: null },
          { id: "b5", kind: "row", label: "Session opened", value: "09:20", tone: "neutral", linkId: null },
        ],
        links: [{ id: "l1", label: "Export", targetId: "audit", variant: "secondary" }],
      },
    ],
  },
];
