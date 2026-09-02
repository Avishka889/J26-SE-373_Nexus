import type { ArchitectureRecommendation } from "@sdlc/contracts-ts";

/**
 * Candidates are deployment shapes, so they can be compared with each other. A
 * code organisation style is a different axis and is not a competing card: it is
 * recorded as a note beside the comparison. Every candidate states its cons, not
 * only its pros, or the score is the only honest thing on the card.
 */
export const seedArchitecture: ArchitectureRecommendation = {
  candidates: [
    {
      id: "modular-monolith",
      name: "Modular Monolith",
      score: 84,
      rationale:
        "Six services in the graph, one team, and a payment flow that needs a transaction across payments, verification and the audit trail. Module boundaries give the separation without the distributed transaction.",
      pros: [
        "One deployment to run and roll back",
        "The payment and audit write stays in one transaction",
        "Boundaries can be split out later if load demands it",
      ],
      cons: [
        "Everything scales together, so a spike in one area costs capacity everywhere",
        "Module boundaries hold only if they are enforced in review",
      ],
    },
    {
      id: "microservices",
      name: "Microservices",
      score: 71,
      rationale:
        "The graph already separates payment, verification and notification cleanly, and the external provider calls are natural seams. The cost is that the payment and audit write becomes distributed.",
      pros: [
        "Each service scales and fails on its own",
        "The verification service can use a different runtime",
        "Matches the service boundaries the graph already shows",
      ],
      cons: [
        "The payment plus audit write needs a saga, since it crosses services",
        "More to operate than one team can comfortably run",
        "Local development needs the whole set running",
      ],
    },
  ],
  recommendedCandidateId: "modular-monolith",
  selectedCandidateId: null,
  selectedAt: null,
  selectedBy: null,
  style: {
    id: "clean",
    name: "Clean Architecture",
    note: "Applies inside whichever shape is chosen: domain logic stays free of framework and provider details, so the payment rules can be tested without Stripe. This is a code organisation style, not a competing deployment shape, which is why it is not scored against the candidates above.",
  },
};
