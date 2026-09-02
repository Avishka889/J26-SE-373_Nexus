import type { ArchitectureRecommendation } from "@sdlc/contracts-ts";

/**
 * ShopFlow's comparison lands the other way from NexusPay's, and it should: the
 * graph here has no transaction that spans services, multi-tenant traffic is the
 * stated performance worry, and the catalog read path scales differently from
 * checkout. That is the case microservices exist for, and the scores say so
 * rather than defaulting to whatever was recommended last time.
 */
export const seedArchitecture: ArchitectureRecommendation = {
  candidates: [
    {
      id: "microservices",
      name: "Microservices",
      score: 82,
      rationale:
        "Catalog reads outnumber checkouts by a wide margin and R-8 asks for one storefront's traffic not to affect another, so the two need to scale apart. Nothing in the graph writes across service boundaries in one transaction, which is what usually makes this shape expensive.",
      pros: [
        "The catalog read path scales without scaling checkout",
        "A slow inventory sync cannot hold up browsing",
        "Matches the service boundaries the graph already shows",
      ],
      cons: [
        "Five services to deploy and watch, for one team",
        "Tenant isolation has to be enforced in every service, not in one place",
        "Local development needs the whole set running",
      ],
    },
    {
      id: "modular-monolith",
      name: "Modular Monolith",
      score: 74,
      rationale:
        "One deployment, and tenant isolation enforced once at the data layer instead of in five services. The cost is that R-8's noisy neighbour worry stays unanswered, because everything shares the same capacity.",
      pros: [
        "Tenant scoping lives in one place, which is easier to prove correct",
        "One deployment to run and roll back",
        "Boundaries can be split out later if load demands it",
      ],
      cons: [
        "Catalog traffic and checkout traffic compete for the same capacity, which R-8 asks them not to",
        "Module boundaries hold only if they are enforced in review",
      ],
    },
    {
      id: "serverless",
      name: "Serverless functions",
      score: 51,
      rationale:
        "Catalog reads are bursty and would suit per request scaling. Carts are not: they are stateful and short lived, and pushing that into a function plus an external store adds a moving part for every read.",
      pros: [
        "Scales to zero between storefront launches",
        "No servers to patch",
      ],
      cons: [
        "Cart state needs an external store, adding a dependency to the hottest path",
        "Cold starts land on the shopper's first page view",
        "Inventory sync is a long running job, which fits functions badly",
      ],
    },
  ],
  recommendedCandidateId: "microservices",
  selectedCandidateId: null,
  selectedAt: null,
  selectedBy: null,
  style: {
    id: "hexagonal",
    name: "Hexagonal Architecture",
    note: "Applies inside whichever shape is chosen: the inventory system and the payment provider sit behind ports, so stock rules can be tested without either. This is a code organisation style, not a competing deployment shape, which is why it is not scored against the candidates above.",
  },
};
