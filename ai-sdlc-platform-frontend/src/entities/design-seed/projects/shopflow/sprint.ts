import type { SprintPlan, UserStory } from "@sdlc/contracts-ts";

/**
 * Estimates only. Nothing has been built, so there is no burndown, no completed
 * points and no per person allocation: showing progress against unwritten code
 * would be fiction.
 *
 * Acceptance criteria are contract rather than decoration, because test
 * generation reads them later.
 */
const stories: UserStory[] = [
  {
    id: "US-201",
    title: "As a shopper, I can browse and filter the catalog",
    epic: "Catalog",
    points: 8,
    priority: "must",
    traces: ["R-1", "R-10"],
    acceptance: [
      {
        id: "AC-201-1",
        given: "a storefront with products in two categories",
        when: "the shopper filters by one category",
        then: "only that category's products are listed, with the count shown",
      },
      {
        id: "AC-201-2",
        given: "a storefront with no products yet",
        when: "the shopper opens the catalog",
        then: "an empty state explains there is nothing listed, rather than showing a spinner",
      },
    ],
  },
  {
    id: "US-202",
    title: "As a shopper, I can put items in a cart and change quantities",
    epic: "Cart",
    points: 5,
    priority: "must",
    traces: ["R-2"],
    acceptance: [
      {
        id: "AC-202-1",
        given: "a cart holding two of an item",
        when: "the shopper sets the quantity to five",
        then: "the cart total updates to five of that item without reloading the page",
      },
      {
        id: "AC-202-2",
        given: "a cart holding one item",
        when: "the shopper sets its quantity to zero",
        then: "the line is removed and the cart reports being empty",
      },
    ],
  },
  {
    id: "US-203",
    title: "As a shopper, I can check out and get a confirmed order",
    epic: "Checkout",
    points: 13,
    priority: "must",
    traces: ["R-3", "R-7", "R-12"],
    acceptance: [
      {
        id: "AC-203-1",
        given: "a cart whose items are all in stock",
        when: "the shopper completes checkout and the provider settles",
        then: "an order is recorded and its number is shown on screen",
      },
      {
        id: "AC-203-2",
        given: "a cart holding more of an item than the recorded stock level",
        when: "the shopper tries to check out",
        then: "checkout is refused, naming the item and the quantity available",
      },
      {
        id: "AC-203-3",
        given: "the payment provider declines",
        when: "the shopper completes checkout",
        then: "no order is recorded and the cart is left as it was",
      },
    ],
  },
  {
    id: "US-204",
    title: "As a merchant, I can see and update order status",
    epic: "Orders",
    points: 8,
    priority: "must",
    traces: ["R-5"],
    acceptance: [
      {
        id: "AC-204-1",
        given: "an order that has been paid for",
        when: "the merchant marks it as shipped",
        then: "the status shows as shipped with the time it changed",
      },
    ],
  },
  {
    id: "US-205",
    title: "As a merchant, my storefront's data is isolated from every other",
    epic: "Multi-tenancy",
    points: 8,
    priority: "must",
    traces: ["R-6", "R-9"],
    acceptance: [
      {
        id: "AC-205-1",
        given: "two storefronts each with their own orders",
        when: "one merchant requests an order id belonging to the other",
        then: "the request is refused as not found, revealing nothing about the other storefront",
      },
    ],
  },
  {
    id: "US-206",
    title: "As a merchant, stock levels follow the inventory system",
    epic: "Inventory",
    points: 5,
    priority: "should",
    traces: ["R-4"],
    acceptance: [
      {
        id: "AC-206-1",
        given: "the inventory system reports a new stock level",
        when: "the sync runs",
        then: "the recorded stock level matches it and the sync time is updated",
      },
    ],
  },
  {
    id: "US-207",
    title: "As a shopper, I can look up a past order without an account",
    epic: "Orders",
    points: 3,
    priority: "could",
    traces: ["R-11"],
    acceptance: [
      {
        id: "AC-207-1",
        given: "an order number and the email it was placed with",
        when: "the shopper looks it up",
        then: "the order status is shown without a sign in",
      },
    ],
  },
];

const proposed = stories.filter((s) => ["US-201", "US-202", "US-203"].includes(s.id));

export const seedSprint: SprintPlan = {
  sprintName: "Sprint 1",
  goal: "A shopper can find a product, put it in a cart and buy it.",
  velocityAssumption: {
    points: 26,
    basis: "Assumed from a team of three over a two week sprint. No history exists yet, so this is an assumption and not a measurement.",
  },
  estimatedPoints: proposed.reduce((total, story) => total + story.points, 0),
  proposed,
  backlog: stories.filter((s) => !proposed.includes(s)),
};
