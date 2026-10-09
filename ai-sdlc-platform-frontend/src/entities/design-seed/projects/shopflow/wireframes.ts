import type { WireframeFlow } from "@sdlc/contracts-ts";

/**
 * Screens are declarative blocks rather than hand written markup, which is what
 * lets a card render a real miniature instead of a placeholder.
 *
 * Breadcrumbs deliberately omit the product name: the player prefixes the
 * project's own name from state, so a fixture cannot hard code a brand.
 *
 * Two stories have no flow on purpose. Tenant isolation and the inventory sync
 * are not screens, and inventing one for each would make the coverage table read
 * as complete when it is not.
 */
export const seedWireframes: WireframeFlow[] = [
  {
    id: "flow-catalog",
    name: "Browse the catalog",
    version: "v1",
    traces: ["R-1", "R-10"],
    coversStoryIds: ["US-201"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "catalog",
        name: "Catalog",
        terminal: false,
        crumbs: ["Shop"],
        blocks: [
          { id: "b1", kind: "text", label: "42 products", value: null, tone: "muted", linkId: null },
          { id: "b2", kind: "row", label: "Category", value: "All", tone: "neutral", linkId: "l2" },
          { id: "b3", kind: "row", label: "Price", value: "Any", tone: "neutral", linkId: "l2" },
          { id: "b4", kind: "list", label: "Trail Runner 40L", value: "128.00", tone: "neutral", linkId: "l1" },
          { id: "b5", kind: "list", label: "Merino Base Layer", value: "74.00", tone: "neutral", linkId: "l1" },
          { id: "b6", kind: "list", label: "Alpine Shell", value: "310.00", tone: "neutral", linkId: "l1" },
        ],
        links: [
          { id: "l1", label: "Open a product", targetId: "product", variant: "row" },
          { id: "l2", label: "Filter", targetId: "catalog", variant: "secondary" },
        ],
      },
      {
        id: "product",
        name: "Product",
        terminal: false,
        crumbs: ["Shop", "Trail Runner 40L"],
        blocks: [
          { id: "b1", kind: "summary", label: "Trail Runner 40L", value: "128.00", tone: "neutral", linkId: null },
          { id: "b2", kind: "text", label: "In stock", value: "7 available", tone: "positive", linkId: null },
          { id: "b3", kind: "field", label: "Quantity", value: "1", tone: "muted", linkId: null },
        ],
        links: [
          { id: "l1", label: "Add to cart", targetId: "catalog", variant: "primary" },
          { id: "l2", label: "Back to the catalog", targetId: "catalog", variant: "text" },
        ],
      },
    ],
  },
  {
    id: "flow-cart",
    name: "Cart",
    version: "v1",
    traces: ["R-2"],
    coversStoryIds: ["US-202"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "cart",
        name: "Cart",
        terminal: false,
        crumbs: ["Cart"],
        blocks: [
          { id: "b1", kind: "list", label: "Trail Runner 40L", value: "2 x 128.00", tone: "neutral", linkId: null },
          { id: "b2", kind: "list", label: "Merino Base Layer", value: "1 x 74.00", tone: "neutral", linkId: null },
          { id: "b3", kind: "summary", label: "Total", value: "330.00", tone: "neutral", linkId: null },
        ],
        links: [
          { id: "l1", label: "Check out", targetId: "cart", variant: "primary" },
          { id: "l2", label: "Keep shopping", targetId: "cart", variant: "text" },
        ],
      },
      {
        id: "cart-empty",
        name: "Empty cart",
        terminal: false,
        crumbs: ["Cart"],
        blocks: [
          { id: "b1", kind: "text", label: "Your cart is empty", value: null, tone: "muted", linkId: null },
        ],
        links: [{ id: "l1", label: "Browse the catalog", targetId: "cart", variant: "primary" }],
      },
    ],
  },
  {
    id: "flow-checkout",
    name: "Checkout",
    version: "v1",
    traces: ["R-3", "R-7", "R-12"],
    coversStoryIds: ["US-203"],
    pendingRefinement: true,
    refinementNote: "Waiting on Q-1: whether an out of stock line blocks checkout or warns.",
    screens: [
      {
        id: "delivery",
        name: "Delivery",
        terminal: false,
        crumbs: ["Checkout", "Delivery"],
        blocks: [
          { id: "b1", kind: "field", label: "Email", value: "you@example.com", tone: "muted", linkId: null },
          { id: "b2", kind: "field", label: "Address", value: "12 Bridge Street", tone: "muted", linkId: null },
          { id: "b3", kind: "field", label: "Postcode", value: "________", tone: "muted", linkId: null },
        ],
        links: [{ id: "l1", label: "Continue to payment", targetId: "payment", variant: "primary" }],
      },
      {
        id: "payment",
        name: "Payment",
        terminal: false,
        crumbs: ["Checkout", "Payment"],
        blocks: [
          { id: "b1", kind: "summary", label: "To pay", value: "330.00", tone: "neutral", linkId: null },
          { id: "b2", kind: "text", label: "Taken by the payment provider", value: null, tone: "muted", linkId: null },
        ],
        links: [
          { id: "l1", label: "Pay now", targetId: "confirmed", variant: "primary" },
          { id: "l2", label: "Back to delivery", targetId: "delivery", variant: "text" },
        ],
      },
      {
        id: "out-of-stock",
        name: "Line out of stock",
        terminal: false,
        crumbs: ["Checkout", "Payment"],
        blocks: [
          {
            id: "b1",
            kind: "banner",
            label: "Trail Runner 40L: only 1 available",
            value: null,
            tone: "muted",
            linkId: "l1",
          },
          { id: "b2", kind: "text", label: "Reduce the quantity to continue", value: null, tone: "muted", linkId: null },
        ],
        links: [{ id: "l1", label: "Back to the cart", targetId: "delivery", variant: "primary" }],
      },
      {
        id: "confirmed",
        name: "Order confirmed",
        terminal: true,
        crumbs: ["Checkout", "Confirmed"],
        blocks: [
          { id: "b1", kind: "summary", label: "Order", value: "SF-10482", tone: "positive", linkId: null },
          { id: "b2", kind: "text", label: "A confirmation is on its way by email", value: null, tone: "muted", linkId: null },
        ],
        links: [{ id: "l1", label: "Keep shopping", targetId: "confirmed", variant: "secondary" }],
      },
    ],
  },
  {
    id: "flow-orders",
    name: "Manage orders",
    version: "v1",
    traces: ["R-5"],
    coversStoryIds: ["US-204"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "orders",
        name: "Orders",
        terminal: false,
        crumbs: ["Orders"],
        blocks: [
          { id: "b1", kind: "list", label: "SF-10482", value: "Paid", tone: "neutral", linkId: "l1" },
          { id: "b2", kind: "list", label: "SF-10481", value: "Shipped", tone: "positive", linkId: "l1" },
          { id: "b3", kind: "list", label: "SF-10480", value: "Refunded", tone: "muted", linkId: "l1" },
        ],
        links: [{ id: "l1", label: "Open an order", targetId: "order", variant: "row" }],
      },
      {
        id: "order",
        name: "Order",
        terminal: false,
        crumbs: ["Orders", "SF-10482"],
        blocks: [
          { id: "b1", kind: "summary", label: "Total", value: "330.00", tone: "neutral", linkId: null },
          { id: "b2", kind: "row", label: "Status", value: "Paid", tone: "neutral", linkId: null },
          { id: "b3", kind: "list", label: "Trail Runner 40L", value: "2", tone: "neutral", linkId: null },
        ],
        links: [
          { id: "l1", label: "Mark as shipped", targetId: "orders", variant: "primary" },
          { id: "l2", label: "Back to orders", targetId: "orders", variant: "text" },
        ],
      },
    ],
  },
  {
    id: "flow-lookup",
    name: "Look up an order",
    version: "v1",
    traces: ["R-11"],
    coversStoryIds: ["US-207"],
    pendingRefinement: false,
    refinementNote: null,
    screens: [
      {
        id: "lookup",
        name: "Find an order",
        terminal: false,
        crumbs: ["Order lookup"],
        blocks: [
          { id: "b1", kind: "field", label: "Order number", value: "SF-10482", tone: "muted", linkId: null },
          { id: "b2", kind: "field", label: "Email", value: "you@example.com", tone: "muted", linkId: null },
        ],
        links: [{ id: "l1", label: "Find it", targetId: "status", variant: "primary" }],
      },
      {
        id: "status",
        name: "Order status",
        terminal: false,
        crumbs: ["Order lookup", "SF-10482"],
        blocks: [
          { id: "b1", kind: "summary", label: "Shipped", value: "2 items", tone: "positive", linkId: null },
        ],
        links: [{ id: "l1", label: "Look up another", targetId: "lookup", variant: "text" }],
      },
    ],
  },
];
