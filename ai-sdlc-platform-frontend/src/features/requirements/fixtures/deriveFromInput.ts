import type { ParsedRequirement } from "../api/types";
import type { ProjectDesignSeed } from "@/entities/design-seed";

/**
 * A small design read from whatever the person typed.
 *
 * This stands in for Component 1 for a project the demo has no authored content
 * for, and it deliberately behaves the way the real component's rule layer does
 * rather than the way a demo would like it to:
 *
 * - The number of requirements comes from how much evidence the input contains,
 *   so a seven word prompt yields a handful, never a confident dozen.
 * - Confidence is low and every requirement is flagged for a closer look,
 *   because a sentence split is not an analysis and should not present itself as
 *   one.
 * - `sourceQuote` is the input's own words, so nothing claims to have been read
 *   from text that is not there.
 * - The assumptions say out loud that this was a literal reading.
 *
 * The four authored projects do not come through here. This is the path for
 * anything created during the session, and it is what makes the generation run
 * produce something a reader can check rather than eight complete stages holding
 * nothing.
 */

const STOP_WORDS = new Set([
  "the", "a", "an", "and", "or", "for", "with", "that", "this", "each", "any", "all", "can",
  "will", "shall", "should", "must", "to", "of", "in", "on", "by", "from", "as", "is", "are",
  "be", "build", "create", "design", "make", "support", "include", "system", "app",
  "application", "platform", "service", "user", "users", "it", "its", "their", "them", "we",
  "our", "so", "then", "when", "if", "at", "into", "over", "up", "down", "out",
  // Words for the container rather than the thing it keeps. "recipe manager"
  // is about recipes; naming the entity "Manager" describes the software back
  // to the person who just described it.
  "manager", "tracker", "tool", "dashboard", "portal", "site", "website", "page",
  "suite", "studio", "client", "server", "software", "product",
]);

/** Sentences, or failing that clauses, since a one line prompt has no full stop. */
function splitInput(text: string): string[] {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (!cleaned) return [];
  const sentences = cleaned
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (sentences.length > 1) return sentences;
  // One sentence: split on the connectives people list features with.
  return cleaned
    .split(/,| and | with | including | plus /i)
    .map((s) => s.trim())
    .filter((s) => s.length > 2);
}

/**
 * The extraction budget, as arithmetic rather than persuasion.
 *
 * Three plus a bit over one per piece of evidence, capped. Instructions about
 * counts are the least reliable thing a language model does, so the real
 * component enforces this by truncation too, and so does this.
 */
function budgetFor(evidence: number): number {
  return Math.max(1, Math.min(8, 2 + Math.round(1.2 * evidence)));
}

/**
 * Words common enough to be describing something rather than naming it.
 *
 * Without this, "Build a simple calculator app" names its entity "Simple",
 * because the adjective comes first and both words appear once. The story then
 * reads "As a user, I can work with a simple", which is not a sentence.
 */
const ADJECTIVES = new Set([
  "simple", "basic", "small", "large", "quick", "fast", "easy", "modern", "clean",
  "nice", "good", "better", "best", "full", "complete", "custom", "personal",
  "private", "public", "smart", "little", "tiny", "huge", "light", "dark", "new",
  "online", "offline", "mobile", "responsive", "minimal", "lightweight",
]);

/**
 * Singular, because an entity is one of a thing.
 *
 * "Track workouts and workout history" mentions the same noun twice in two
 * forms; counting them apart both undercounts it and names the entity
 * "Workouts", where every authored seed says Product, Cart, Order.
 */
function singular(word: string): string {
  if (word.length > 4 && word.endsWith("ies")) return `${word.slice(0, -3)}y`;
  if (word.length > 4 && word.endsWith("ses")) return word.slice(0, -2);
  if (word.length > 4 && word.endsWith("s") && !word.endsWith("ss")) return word.slice(0, -1);
  return word;
}

/** The nouns the input actually used, for naming the entity and the screens. */
function keyNouns(text: string): string[] {
  const words = text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 3 && !STOP_WORDS.has(w) && !ADJECTIVES.has(w))
    .map(singular);
  const counts = new Map<string, number>();
  for (const word of words) counts.set(word, (counts.get(word) ?? 0) + 1);
  // Repetition first, then length. A word the input used twice is what this is
  // about; between two used once, the longer one is the more specific noun far
  // more often than not.
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || b[0].length - a[0].length)
    .map(([word]) => word);
}

const titleCase = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

/** A sentence turned into something that reads as a requirement. */
function asRequirement(fragment: string): string {
  const trimmed = fragment.replace(/^(and|with|plus|including)\s+/i, "").trim();
  const sentence = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`;
}

export function deriveSeedFromInput(projectName: string, text: string): ProjectDesignSeed {
  const fragments = splitInput(text);
  const kept = fragments.slice(0, budgetFor(fragments.length));
  const nouns = keyNouns(text);
  const thing = titleCase(nouns[0] ?? "Record");
  const secondary = titleCase(nouns[1] ?? "Detail");

  const requirements: ParsedRequirement[] = kept.map((fragment, i) => ({
    id: `R-${i + 1}`,
    text: asRequirement(fragment),
    type: "functional" as const,
    priority: i === 0 ? ("must" as const) : ("should" as const),
    // Deliberately low. A sentence split is not an analysis, and the number says
    // so rather than flattering the demo.
    confidence: 44 - Math.min(i * 3, 12),
    qualityAttribute: null,
    lowConfidence: true,
    adjusted: false,
    sourceQuote: fragment,
  }));

  if (requirements.length === 0) {
    requirements.push({
      id: "R-1",
      text: "The system does what the requirement text describes.",
      type: "functional",
      priority: "must",
      confidence: 20,
      qualityAttribute: null,
      lowConfidence: true,
      adjusted: false,
      sourceQuote: null,
    });
  }

  const allIds = requirements.map((r) => r.id);
  const firstId = allIds[0];

  return {
    appName: projectName.split(" ")[0] || "App",

    requirements,

    assumptions: [
      {
        id: "A-1",
        text: "Assumed a single user role, since the input does not distinguish between the people who use this.",
        traces: [firstId],
        dismissed: false,
        edited: false,
      },
      {
        id: "A-2",
        text: "Read your input literally, one requirement per statement. Nothing was inferred beyond the words you wrote, which is why every confidence here is low.",
        traces: allIds.slice(0, 3),
        dismissed: false,
        edited: false,
      },
    ],

    questions: [
      {
        id: "Q-1",
        question: `Who uses this, and is there more than one kind of person involved?`,
        traces: [firstId],
        answer: null,
        answeredAt: null,
      },
      {
        id: "Q-2",
        question: `Does a ${thing.toLowerCase()} need to be kept between sessions, or is it enough to hold it while the app is open?`,
        traces: allIds.slice(0, 2),
        answer: null,
        answeredAt: null,
      },
    ],

    nodes: [
      {
        id: "a1",
        kind: "actor",
        label: "User",
        description: "Whoever uses this. The input does not say more than that yet.",
        position: { x: 0, y: 140 },
        traces: [firstId],
        attributes: [],
        actorKind: "primary",
        standard: null,
        appliesTo: [],
        unconfirmed: {
          ruleId: "actor-is-named",
          reason:
            "No requirement names who uses this, so the actor is a placeholder rather than something read from your input. Q-1 is asking.",
          traces: [firstId],
        },
        changedInVersion: null,
      },
      {
        id: "m1",
        kind: "service",
        label: `${thing} Service`,
        description: `Handles whatever happens to a ${thing.toLowerCase()}.`,
        position: { x: 340, y: 140 },
        traces: allIds.slice(0, 3),
        attributes: [],
        actorKind: null,
        standard: null,
        appliesTo: [],
        unconfirmed: null,
        changedInVersion: null,
      },
      {
        id: "e1",
        kind: "entity",
        label: thing,
        description: `The main thing this keeps, named from your input.`,
        position: { x: 700, y: 80 },
        traces: [firstId],
        attributes: [
          { name: "id", type: "UUID" },
          { name: "createdAt", type: "Timestamp" },
        ],
        actorKind: null,
        standard: null,
        appliesTo: [],
        unconfirmed: null,
        changedInVersion: null,
      },
      {
        id: "e2",
        kind: "entity",
        label: secondary,
        description: `A second thing your input mentions alongside the ${thing.toLowerCase()}.`,
        position: { x: 700, y: 240 },
        traces: allIds.slice(0, 2),
        attributes: [{ name: "id", type: "UUID" }],
        actorKind: null,
        standard: null,
        appliesTo: [],
        unconfirmed: null,
        changedInVersion: null,
      },
    ],

    edges: [
      { id: "x1", source: "a1", target: "e1", kind: "action", verb: "creates", traces: [firstId] },
      { id: "x2", source: "a1", target: "e2", kind: "action", verb: "reads", traces: allIds.slice(0, 2) },
      { id: "d1", source: "m1", target: "e1", kind: "data", verb: "owns", traces: [firstId] },
      { id: "d2", source: "m1", target: "e2", kind: "data", verb: "owns", traces: allIds.slice(0, 2) },
    ],

    architecture: {
      candidates: [
        {
          id: "modular-monolith",
          name: "Modular Monolith",
          score: 78,
          rationale: `One service and ${requirements.length} requirements. Nothing here asks for parts that scale apart, and a single deployment is the least you can get wrong.`,
          pros: ["One deployment to run and roll back", "No network call between parts that always change together"],
          cons: [
            "Everything scales together",
            "Scored on very little: with this much input the comparison is weak, and the score says so",
          ],
        },
        {
          id: "microservices",
          name: "Microservices",
          score: 34,
          rationale:
            "Nothing in the input separates two things that would deploy or scale independently, so the split would be guesswork.",
          pros: ["Parts could scale on their own later"],
          cons: [
            "No boundary in the input to split along",
            "More to operate than this scope needs",
          ],
        },
      ],
      recommendedCandidateId: "modular-monolith",
      selectedCandidateId: null,
      selectedAt: null,
      selectedBy: null,
      style: {
        id: "layered",
        name: "Layered Architecture",
        note: "Applies inside whichever shape is chosen. This is a code organisation style, not a competing deployment shape, which is why it is not scored against the candidates above.",
      },
    },

    useCases: [
      {
        id: "uc-main",
        name: `Work with a ${thing.toLowerCase()}`,
        traces: [firstId],
        storyId: "US-1",
        steps: [
          { fromId: "a1", toId: "m1", message: `asks for a {e1}`, kind: "call" },
          { fromId: "m1", toId: "m1", message: `record the {e1}`, kind: "call" },
          { fromId: "m1", toId: "a1", message: "confirms it", kind: "return" },
          {
            fromId: "m1",
            toId: "m1",
            message: "read from a single statement, so the real interaction is probably longer",
            kind: "note",
          },
        ],
      },
    ],

    diagrams: [
      {
        id: "class",
        kind: "class",
        title: "Class Diagram",
        description: "The entities and the service that owns them, generated from the graph.",
        source: null,
        useCaseId: null,
        traces: [firstId],
      },
      {
        id: "er",
        kind: "er",
        title: "Entity Relationship Diagram",
        description: "The same entities as stored data, generated from the graph.",
        source: null,
        useCaseId: null,
        traces: [firstId],
      },
      {
        id: "sequence",
        kind: "sequence",
        title: "Sequence Diagram",
        description: "The one interaction the input supports, with names read from the graph.",
        source: null,
        useCaseId: "uc-main",
        traces: [firstId],
      },
    ],

    flows: [
      {
        id: "flow-main",
        name: thing,
        version: "v1",
        traces: [firstId],
        coversStoryIds: ["US-1"],
        pendingRefinement: false,
        refinementNote: null,
        screens: [
          {
            id: "list",
            name: `${thing} list`,
            terminal: false,
            crumbs: [thing],
            blocks: [
              { id: "b1", kind: "text", label: `Your ${thing.toLowerCase()}s`, value: null, tone: "neutral", linkId: null },
              { id: "b2", kind: "list", label: `First ${thing.toLowerCase()}`, value: null, tone: "neutral", linkId: "l1" },
              { id: "b3", kind: "list", label: `Second ${thing.toLowerCase()}`, value: null, tone: "neutral", linkId: "l1" },
            ],
            links: [
              { id: "l1", label: "Open it", targetId: "detail", variant: "row" },
              { id: "l2", label: `New ${thing.toLowerCase()}`, targetId: "detail", variant: "primary" },
            ],
          },
          {
            id: "detail",
            name: thing,
            terminal: false,
            crumbs: [thing, "Detail"],
            blocks: [
              { id: "b1", kind: "field", label: "Name", value: "________", tone: "muted", linkId: null },
              { id: "b2", kind: "summary", label: secondary, value: null, tone: "neutral", linkId: null },
            ],
            links: [{ id: "l1", label: "Save", targetId: "list", variant: "primary" }],
          },
        ],
      },
    ],

    sprint: {
      sprintName: "Sprint 1",
      goal: `Get the first ${thing.toLowerCase()} working end to end.`,
      velocityAssumption: {
        points: 20,
        basis: "assumed rather than measured, since no history exists for this project yet",
      },
      estimatedPoints: 5 + requirements.length,
      proposed: [
        {
          id: "US-1",
          title: `As a user, I can work with a ${thing.toLowerCase()}`,
          epic: thing,
          points: 5 + requirements.length,
          priority: "must",
          traces: allIds,
          acceptance: [
            {
              id: "AC-1-1",
              given: "a user with nothing recorded yet",
              when: `they create a ${thing.toLowerCase()}`,
              then: "it is recorded and shown back to them",
            },
            {
              id: "AC-1-2",
              given: "these criteria were read from a short input",
              when: "the requirements are filled in properly",
              then: "they are expected to change, which is what the low confidence figures are saying",
            },
          ],
        },
      ],
      backlog: [
        {
          id: "US-2",
          title: "As a user, I know who else can see this",
          epic: "Access",
          points: 3,
          priority: "could",
          traces: [firstId],
          acceptance: [
            {
              id: "AC-2-1",
              given: "more than one kind of person uses this",
              when: "Q-1 has been answered",
              then: "this story is replaced by real requirements for each role",
            },
          ],
        },
      ],
    },
  };
}
