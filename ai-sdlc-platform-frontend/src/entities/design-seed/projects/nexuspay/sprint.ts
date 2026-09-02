import type { SprintPlan, UserStory } from "@sdlc/contracts-ts";

/**
 * A design phase plans work; it does not report on work. There is no burndown,
 * no completed points and no per person allocation here, because nothing has
 * been built yet and showing progress against unwritten code would be fiction.
 *
 * Points are estimates and are labelled as such. Acceptance criteria are part of
 * the contract, not decoration: test generation reads them later.
 */
const stories: UserStory[] = [
  {
    id: "US-101",
    title: "As a customer, I can pay with a saved card",
    epic: "Payments",
    points: 8,
    priority: "must",
    traces: ["R-1", "R-2"],
    acceptance: [
      {
        id: "AC-101-1",
        given: "a signed in customer with a saved card",
        when: "they confirm a payment below the verification threshold",
        then: "the payment is charged and confirmed on screen within two seconds",
      },
      {
        id: "AC-101-2",
        given: "the provider declines the card",
        when: "the customer confirms the payment",
        then: "the payment is recorded as failed and the reason is shown without retrying automatically",
      },
    ],
  },
  {
    id: "US-102",
    title: "As a customer, I can pay with a digital wallet",
    epic: "Payments",
    points: 13,
    priority: "must",
    traces: ["R-1", "R-2"],
    acceptance: [
      {
        id: "AC-102-1",
        given: "a customer on a device with a wallet available",
        when: "they choose the wallet and authorise the payment",
        then: "the payment is charged without the platform ever receiving the card number",
      },
    ],
  },
  {
    id: "US-103",
    title: "As a customer, I verify my identity before a large payment",
    epic: "Verification",
    points: 21,
    priority: "must",
    traces: ["R-3"],
    acceptance: [
      {
        id: "AC-103-1",
        given: "a customer who has not been verified",
        when: "they start a payment above the threshold",
        then: "the payment is held and they are asked for an identity document",
      },
      {
        id: "AC-103-2",
        given: "a held payment and an approved document",
        when: "the review completes",
        then: "the held payment continues without the customer entering it again",
      },
    ],
  },
  {
    id: "US-104",
    title: "As an administrator, I review submitted documents",
    epic: "Verification",
    points: 5,
    priority: "should",
    traces: ["R-4", "R-5"],
    acceptance: [
      {
        id: "AC-104-1",
        given: "documents waiting for review",
        when: "an administrator approves or rejects one",
        then: "the outcome is recorded in the audit trail with the reviewer's name",
      },
    ],
  },
  {
    id: "US-105",
    title: "As a customer, I am told whether my payment worked",
    epic: "Notifications",
    points: 3,
    priority: "should",
    traces: ["R-6"],
    acceptance: [
      {
        id: "AC-105-1",
        given: "a payment that has settled or failed",
        when: "the outcome is recorded",
        then: "the customer receives a notification naming the amount and the outcome",
      },
      {
        id: "AC-105-2",
        given: "the notification service is unavailable",
        when: "a payment settles",
        then: "the payment still completes and the notification is retried later",
      },
    ],
  },
  {
    id: "US-106",
    title: "As a customer, I can see my past transactions",
    epic: "Payments",
    points: 8,
    priority: "could",
    traces: ["R-7"],
    acceptance: [
      {
        id: "AC-106-1",
        given: "a customer with past payments",
        when: "they open their history",
        then: "payments are listed newest first with amount, method and outcome",
      },
    ],
  },
  {
    id: "US-107",
    title: "As a compliance officer, I can read an unedited audit trail",
    epic: "Compliance",
    points: 5,
    priority: "must",
    traces: ["R-5", "R-9"],
    acceptance: [
      {
        id: "AC-107-1",
        given: "any recorded action",
        when: "someone attempts to change or delete the entry",
        then: "the attempt is refused and itself recorded",
      },
    ],
  },
];

const priorityRank = { must: 0, should: 1, could: 2 } as const;
const byPriority = (a: UserStory, b: UserStory) => priorityRank[a.priority] - priorityRank[b.priority];

const proposed = stories.filter((s) => ["US-101", "US-103", "US-104"].includes(s.id)).sort(byPriority);
const backlog = stories.filter((s) => !proposed.some((p) => p.id === s.id)).sort(byPriority);

export const seedSprint: SprintPlan = {
  sprintName: "Sprint 1 (proposed)",
  goal: "A customer can pay, and a payment above the threshold is verified first.",
  velocityAssumption: {
    points: 34,
    basis: "assumed for a new team of four, with no delivered sprint to measure yet",
  },
  estimatedPoints: proposed.reduce((sum, s) => sum + s.points, 0),
  proposed,
  backlog,
};
