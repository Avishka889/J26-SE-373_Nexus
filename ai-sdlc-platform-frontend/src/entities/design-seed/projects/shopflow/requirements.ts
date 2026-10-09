import type { Assumption, ParsedRequirement } from "@sdlc/contracts-ts";

/**
 * ShopFlow Commerce, read from its own brief: a headless commerce platform with
 * catalog, cart, checkout, inventory sync and order management across
 * multi-tenant storefronts.
 *
 * Nothing here mentions payments beyond taking one, and nothing mentions
 * identity verification, because that brief does not. Confidence is per
 * requirement and the low ones are the ones the input genuinely left vague.
 */
export const seedRequirements: ParsedRequirement[] = [
  {
    id: "R-1",
    text: "A shopper can browse a product catalog and filter it by category and price.",
    type: "functional",
    priority: "must",
    confidence: 95,
    qualityAttribute: null,
    lowConfidence: false,
    adjusted: false,
    sourceQuote: "Create a headless e-commerce platform with product catalog",
  },
  {
    id: "R-2",
    text: "A shopper can add items to a cart and change quantities before checking out.",
    type: "functional",
    priority: "must",
    confidence: 94,
    qualityAttribute: null,
    lowConfidence: false,
    adjusted: false,
    sourceQuote: "product catalog, cart, checkout",
  },
  {
    id: "R-3",
    text: "A shopper can complete checkout and receives an order confirmation.",
    type: "functional",
    priority: "must",
    confidence: 93,
    qualityAttribute: null,
    lowConfidence: false,
    adjusted: false,
    sourceQuote: "cart, checkout, inventory sync and order management",
  },
  {
    id: "R-4",
    text: "Stock levels are kept in step with an external inventory system.",
    type: "functional",
    priority: "must",
    confidence: 72,
    qualityAttribute: null,
    lowConfidence: true,
    adjusted: false,
    sourceQuote: "inventory sync",
  },
  {
    id: "R-5",
    text: "A merchant can see and update the status of an order.",
    type: "functional",
    priority: "must",
    confidence: 88,
    qualityAttribute: null,
    lowConfidence: false,
    adjusted: false,
    sourceQuote: "order management",
  },
  {
    id: "R-6",
    text: "Each storefront serves its own catalog, branding and orders, isolated from the others.",
    type: "functional",
    priority: "must",
    confidence: 90,
    qualityAttribute: null,
    lowConfidence: false,
    adjusted: false,
    sourceQuote: "Support multi-tenant storefronts.",
  },
  {
    id: "R-7",
    text: "A shopper cannot check out more of an item than is in stock.",
    type: "constraint",
    priority: "must",
    confidence: 64,
    qualityAttribute: null,
    lowConfidence: true,
    adjusted: false,
    sourceQuote: null,
  },
  {
    id: "R-8",
    text: "One storefront's traffic cannot degrade another storefront's response times.",
    type: "quality",
    priority: "should",
    confidence: 58,
    qualityAttribute: "performance",
    lowConfidence: true,
    adjusted: false,
    sourceQuote: null,
  },
  {
    id: "R-9",
    text: "A storefront's data is never readable from another storefront.",
    type: "quality",
    priority: "must",
    confidence: 81,
    qualityAttribute: "security",
    lowConfidence: false,
    adjusted: false,
    sourceQuote: "Support multi-tenant storefronts.",
  },
  {
    id: "R-10",
    text: "The catalog is reachable over an API by any front end, with no server rendered pages required.",
    type: "constraint",
    priority: "must",
    confidence: 87,
    qualityAttribute: null,
    lowConfidence: false,
    adjusted: false,
    sourceQuote: "Create a headless e-commerce platform",
  },
  {
    id: "R-11",
    text: "A shopper can look up a past order without signing in to an account.",
    type: "functional",
    priority: "could",
    confidence: 41,
    qualityAttribute: null,
    lowConfidence: true,
    adjusted: false,
    sourceQuote: null,
  },
  {
    id: "R-12",
    text: "Payment for an order is taken through an external payment provider.",
    type: "functional",
    priority: "must",
    confidence: 69,
    qualityAttribute: null,
    lowConfidence: true,
    adjusted: false,
    sourceQuote: null,
  },
];

export const seedAssumptions: Assumption[] = [
  {
    id: "A-1",
    text: "Assumed inventory sync is one way, from the external system into ShopFlow, with ShopFlow never writing stock back.",
    traces: ["R-4"],
    dismissed: false,
    edited: false,
  },
  {
    id: "A-2",
    text: "Assumed storefronts share one deployment and are separated by a tenant id, rather than each getting its own database.",
    traces: ["R-6", "R-9"],
    dismissed: false,
    edited: false,
  },
  {
    id: "A-3",
    text: "Assumed a single currency per storefront, with no conversion at checkout.",
    traces: ["R-3", "R-12"],
    dismissed: false,
    edited: false,
  },
];

export const seedQuestions = [
  {
    id: "Q-1",
    question:
      "When the external inventory system says an item went out of stock while it was in someone's cart, should checkout block or warn and continue?",
    traces: ["R-4", "R-7"],
    answer: null,
    answeredAt: null,
    presetAnswer: "Block it. Selling stock we do not have costs more than a lost cart.",
  },
  {
    id: "Q-2",
    question: "Does a shopper need an account, or is guest checkout enough for the first release?",
    traces: ["R-3", "R-11"],
    answer: null,
    answeredAt: null,
    presetAnswer: "Guest checkout only for the first release. Accounts come later.",
  },
];
