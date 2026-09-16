import { CODE_STAGE_IDS, type CodeStageId } from "@/types/project";
import type { ProjectDesignSeed } from "@/entities/design-seed";
import type {
  ApiContract,
  ApiEndpoint,
  CodeSnapshot,
  CodeStages,
  CodeThreadMessage,
  EntityModel,
  ManifestRow,
  SprintScope,
  TechStackArtefact,
} from "../api/types";

/**
 * The code phase's demo content, derived from the project's own design seed.
 *
 * Derived rather than authored, and that is the point: every endpoint here
 * traces to screen ids, requirement ids and story ids that exist in this
 * project's design, so the traceability chips resolve to something real
 * instead of to plausible looking strings. A coherence test asserts exactly
 * that, because a demo whose traces go nowhere is a demo of the wrong thing.
 *
 * This is not the rule arm. It is a deliberately simpler mapping that produces
 * the same *shape*: entities become resources, action edges become writes,
 * screens ground them. The real inference lives in C2 and is what runs when
 * the feature is flipped live; this exists so the phase can be read, demoed
 * and end to end tested without a model, a database or a minute of waiting.
 */

export type CodePosture =
  /** The design has not been approved, so nothing may be generated yet. */
  | "not-started"
  /** Generated, waiting on the review. The state the demo spends its time in. */
  | "awaiting"
  /** The review was approved: read only, and the phase after it has started. */
  | "approved";

const CREATE_VERBS = [
  "create",
  "add",
  "place",
  "submit",
  "send",
  "start",
  "book",
  "raise",
  "make",
];
const UPDATE_VERBS = [
  "update",
  "edit",
  "change",
  "approve",
  "confirm",
  "assign",
  "resolve",
];
const DELETE_VERBS = ["delete", "remove", "cancel", "revoke"];

function singular(word: string): string {
  if (word.endsWith("ies") && word.length > 3) return `${word.slice(0, -3)}y`;
  if (word.endsWith("ss")) return word;
  if (word.endsWith("s")) return word.slice(0, -1);
  return word;
}

function kebab(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function plural(word: string): string {
  if (word.endsWith("y") && !"aeiou".includes(word.slice(-2, -1)))
    return `${word.slice(0, -1)}ies`;
  if (/(s|x|z|ch|sh)$/.test(word)) return `${word}es`;
  return `${word}s`;
}

function resourceOf(label: string): string {
  const parts = kebab(label).split("-");
  parts[parts.length - 1] = plural(parts[parts.length - 1]);
  return parts.join("-");
}

function methodFor(verb: string): "POST" | "PUT" | "PATCH" | "DELETE" | "GET" {
  const words = kebab(verb).split("-").map(singular);
  if (words.some((w) => CREATE_VERBS.includes(w))) return "POST";
  if (words.some((w) => UPDATE_VERBS.includes(w))) return "PATCH";
  if (words.some((w) => DELETE_VERBS.includes(w))) return "DELETE";
  return "GET";
}

function fieldType(
  attributeType: string,
): "string" | "number" | "boolean" | "date" | "id" {
  const type = attributeType.toLowerCase();
  if (
    ["int", "integer", "number", "float", "decimal", "money", "count"].includes(
      type,
    )
  )
    return "number";
  if (["bool", "boolean", "flag"].includes(type)) return "boolean";
  if (["date", "datetime", "timestamp", "time"].includes(type)) return "date";
  return "string";
}

/** Screens whose name or blocks name this entity, as `flowId/screenId`. */
function screensAbout(seed: ProjectDesignSeed, label: string): string[] {
  const noun = singular(kebab(label).split("-").pop() ?? "");
  if (!noun) return [];
  const found: string[] = [];
  for (const flow of seed.flows) {
    for (const screen of flow.screens) {
      const haystack = [
        screen.name,
        ...screen.blocks.map((b) => b.label),
        ...screen.links.map((l) => l.label),
      ]
        .join(" ")
        .toLowerCase();
      if (
        haystack.split(/[^a-z0-9]+/).some((word) => singular(word) === noun)
      ) {
        found.push(`${flow.id}/${screen.id}`);
      }
    }
  }
  return found;
}

function storiesFor(
  seed: ProjectDesignSeed,
  requirementIds: string[],
): string[] {
  const wanted = new Set(requirementIds);
  return [...seed.sprint.proposed, ...seed.sprint.backlog]
    .filter((story) => story.traces.some((trace) => wanted.has(trace)))
    .map((story) => story.id);
}

/**
 * Confidence, computed rather than chosen.
 *
 * The same shape the rule arm uses: grounding in real screens is what raises
 * it, and the ceiling is below 100 because nothing inferred is certain.
 */
function confidenceOf(screenIds: string[], storyIds: string[]): number {
  let score = 70;
  if (screenIds.length) score += 18;
  if (storyIds.length) score += 10;
  return Math.min(score, 98);
}

function buildContract(seed: ProjectDesignSeed, version: number): ApiContract {
  const entityNodes = seed.nodes.filter((node) => node.kind === "entity");
  const actors = new Map(
    seed.nodes
      .filter((node) => node.kind === "actor")
      .map((node) => [node.id, node.label]),
  );

  // A field states no bounds unless a rule read them; the contract's type asks
  // for each one all the same.
  const unbounded = {
    minimum: null,
    maximum: null,
    minLength: null,
    maxLength: null,
    oneOf: [],
    rules: [],
  };
  const entities: EntityModel[] = entityNodes.map((node) => ({
    name: node.label,
    fields: [
      { name: "id", type: "id", required: true, itemRef: "", ...unbounded },
      ...(node.attributes ?? []).map((attribute) => ({
        name: attribute.name,
        type: fieldType(attribute.type),
        required: true,
        itemRef: "",
        ...unbounded,
      })),
    ],
    traces: [...node.traces],
  }));

  const byKey = new Map<string, ApiEndpoint>();
  const add = (endpoint: ApiEndpoint) => {
    const key = `${endpoint.method} ${endpoint.path}`;
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, endpoint);
      return;
    }
    // Two edges can describe one endpoint. Union the evidence rather than
    // keeping the first and losing the second's traces.
    existing.traces = {
      screenIds: [
        ...new Set([
          ...existing.traces.screenIds,
          ...endpoint.traces.screenIds,
        ]),
      ],
      actionIds: [
        ...new Set([
          ...existing.traces.actionIds,
          ...endpoint.traces.actionIds,
        ]),
      ],
      storyIds: [
        ...new Set([...existing.traces.storyIds, ...endpoint.traces.storyIds]),
      ],
      requirementIds: [
        ...new Set([
          ...existing.traces.requirementIds,
          ...endpoint.traces.requirementIds,
        ]),
      ],
    };
    existing.authActors = [
      ...new Set([...existing.authActors, ...endpoint.authActors]),
    ];
  };

  for (const node of entityNodes) {
    const resource = resourceOf(node.label);
    const screenIds = screensAbout(seed, node.label);
    const requirementIds = [...node.traces];
    const storyIds = storiesFor(seed, requirementIds);
    const traces = { screenIds, actionIds: [], storyIds, requirementIds };
    const responseFields =
      entities.find((entity) => entity.name === node.label)?.fields ?? [];

    add({
      id: `get-${resource}`,
      method: "GET",
      path: `/${resource}`,
      summary: `List ${resource.replace(/-/g, " ")}`,
      authActors: [],
      request: null,
      response: { entity: node.label, fields: responseFields },
      validation: [],
      traces,
      origin: "rule",
      confidence: confidenceOf(screenIds, storyIds),
    });
    add({
      id: `get-${resource}-id`,
      method: "GET",
      path: `/${resource}/{id}`,
      summary: `Read one ${singular(node.label.toLowerCase())}`,
      authActors: [],
      request: null,
      response: { entity: node.label, fields: responseFields },
      validation: [],
      traces,
      origin: "rule",
      confidence: confidenceOf(screenIds, storyIds),
    });
  }

  for (const edge of seed.edges) {
    if (edge.kind !== "action") continue;
    const entity = entityNodes.find((node) => node.id === edge.target);
    const actor = actors.get(edge.source);
    if (!entity) continue;

    const resource = resourceOf(entity.label);
    const method = methodFor(edge.verb);
    const screenIds = screensAbout(seed, entity.label);
    const requirementIds = [...new Set([...edge.traces, ...entity.traces])];
    const storyIds = storiesFor(seed, requirementIds);
    const actionIds = seed.flows
      .flatMap((flow) =>
        flow.screens.filter((s) => screenIds.includes(`${flow.id}/${s.id}`)),
      )
      .flatMap((screen) => screen.links.map((link) => link.id));
    const fields = entities.find((e) => e.name === entity.label)?.fields ?? [];
    const constraints = seed.nodes
      .filter(
        (node) =>
          node.kind === "constraint" &&
          (node.appliesTo ?? []).includes(entity.id),
      )
      .map((node) => node.label);

    add({
      id: `${method.toLowerCase()}-${resource}${method === "GET" ? "" : method === "POST" ? "" : "-id"}`,
      method,
      path:
        method === "POST" || method === "GET"
          ? `/${resource}`
          : `/${resource}/{id}`,
      summary: `${edge.verb.charAt(0).toUpperCase()}${edge.verb.slice(1)} ${singular(entity.label.toLowerCase())}`,
      authActors: actor ? [actor] : [],
      request:
        method === "GET" || method === "DELETE"
          ? null
          : {
              entity: entity.label,
              fields: fields.filter((field) => field.name !== "id"),
            },
      response: { entity: entity.label, fields },
      validation: method === "GET" ? [] : constraints,
      traces: {
        screenIds,
        actionIds: [...new Set(actionIds)],
        storyIds,
        requirementIds,
      },
      origin: "rule",
      confidence: confidenceOf(screenIds, storyIds),
    });
  }

  return {
    version,
    entities,
    endpoints: [...byKey.values()].sort((a, b) => a.id.localeCompare(b.id)),
  };
}

function buildScope(seed: ProjectDesignSeed): SprintScope {
  const covered = new Map(seed.flows.map((flow) => [flow.id, flow]));
  const screensFor = (storyId: string) =>
    [...covered.values()]
      .filter((flow) => (flow.coversStoryIds ?? []).includes(storyId))
      .flatMap((flow) =>
        flow.screens.map((screen) => `${flow.id}/${screen.id}`),
      );

  return {
    sprintName: seed.sprint.sprintName,
    stories: [
      ...seed.sprint.proposed.map((story) => ({
        id: story.id,
        title: story.title,
        points: story.points,
        inScope: true,
        sprint: 1,
        decidedBy: "system default",
        traces: {
          requirementIds: [...story.traces],
          screenIds: screensFor(story.id),
        },
      })),
      ...seed.sprint.backlog.map((story) => ({
        id: story.id,
        title: story.title,
        points: story.points,
        inScope: false,
        sprint: 0,
        decidedBy: "system default",
        traces: {
          requirementIds: [...story.traces],
          screenIds: screensFor(story.id),
        },
      })),
    ],
  };
}

function buildStack(seed: ProjectDesignSeed): TechStackArtefact {
  const entities = seed.nodes.filter((node) => node.kind === "entity").length;
  const services = seed.nodes.filter((node) => node.kind === "service").length;
  const external = seed.nodes.filter(
    (node) => node.actorKind === "external_system",
  ).length;

  return {
    facts: [
      { label: "entities", value: entities },
      { label: "services", value: services },
      { label: "external systems", value: external },
      {
        label: "named standards",
        value: seed.nodes.filter((n) => n.kind === "constraint").length,
      },
    ],
    candidates: [
      {
        id: "mern",
        name: "MERN",
        layers: [
          { name: "frontend", choice: "React", version: "19", rationale: "" },
          { name: "backend", choice: "Express", version: "5", rationale: "" },
          { name: "database", choice: "MongoDB", version: "", rationale: "" },
          {
            name: "language",
            choice: "TypeScript",
            version: "",
            rationale: "",
          },
        ],
        score: Math.min(60 + entities * 2, 92),
        scoreBreakdown: [
          { label: "baseline", points: 60 },
          {
            label: `${entities} entities in one bounded design`,
            points: Math.min(entities * 2, 32),
          },
        ],
        explanation:
          "One language across both sides and one thing to deploy, which suits a design with no service boundaries to respect.",
        available: true,
        unavailableReason: null,
      },
      {
        id: "react-spring-postgres",
        name: "React and Spring Boot",
        layers: [
          { name: "frontend", choice: "React", version: "19", rationale: "" },
          {
            name: "backend",
            choice: "Spring Boot",
            version: "3",
            rationale: "",
          },
          {
            name: "database",
            choice: "PostgreSQL",
            version: "16",
            rationale: "",
          },
        ],
        score: Math.min(52 + services * 6, 88),
        scoreBreakdown: [
          { label: "baseline", points: 52 },
          {
            label: `${services} services with their own data`,
            points: Math.min(services * 6, 36),
          },
        ],
        explanation: "",
        // Shown honestly rather than hidden: the platform can score this stack
        // and cannot yet generate it, and saying so is the whole point.
        available: false,
        unavailableReason:
          "generators not built yet; lands before the Java work in Testing",
      },
    ],
    recommendedId: "mern",
    selectedId: "mern",
    selectedBy: "system default",
    selectedAt: null,
  };
}

/** A row as the demo writes it; no page here was rewritten by a model or kept from an earlier one. */
type DemoRow = Omit<
  ManifestRow,
  "writtenFrom" | "reusedFromVersion" | "carriedFixes"
>;

function fileSet(contract: ApiContract, appName: string): ManifestRow[] {
  const rows: DemoRow[] = [
    {
      path: "package.json",
      stage: "build",
      generator: "static",
      arm: "rule",
      implements: [],
      summary: "Monorepo scaffold.",
    },
    {
      path: "README.md",
      stage: "build",
      generator: "rule",
      arm: "rule",
      implements: [],
      summary: `Names ${appName}, the design version and the arm.`,
    },
    {
      path: "packages/contract/src/types.ts",
      stage: "frontend-code",
      generator: "rule",
      arm: "rule",
      implements: contract.entities.map((entity) => entity.name),
      summary: "The shared types both sides agree through.",
    },
    {
      path: "packages/contract/src/client.ts",
      stage: "frontend-code",
      generator: "rule",
      arm: "rule",
      implements: contract.endpoints.map((endpoint) => endpoint.id),
      summary: "One typed method per contract endpoint.",
    },
  ];

  const resources = [
    ...new Set(contract.endpoints.map((e) => e.path.split("/")[1])),
  ];
  for (const resource of resources) {
    const implemented = contract.endpoints
      .filter((endpoint) => endpoint.path.split("/")[1] === resource)
      .map((endpoint) => endpoint.id);
    rows.push({
      path: `apps/api/src/routes/${resource}.ts`,
      stage: "backend-code",
      generator: "rule",
      arm: "rule",
      implements: implemented,
      summary: `Routes for /${resource}, each with an implements header.`,
    });
    rows.push({
      path: `apps/api/src/__tests__/${resource}.contract.test.ts`,
      stage: "backend-code",
      generator: "rule",
      arm: "rule",
      implements: implemented,
      summary: `One test per endpoint on /${resource}.`,
    });
  }
  for (const entity of contract.entities) {
    rows.push({
      path: `apps/api/src/models/${entity.name.replace(/[^A-Za-z0-9]/g, "")}.ts`,
      stage: "backend-code",
      generator: "rule",
      arm: "rule",
      implements: [entity.name],
      summary: "The entity model and its repository interface.",
    });
  }
  return rows.map((row) => ({
    ...row,
    writtenFrom: "",
    reusedFromVersion: 0,
    carriedFixes: [],
  }));
}

const CODE_VERSION = 1;

export function buildCodeSnapshot(
  projectId: string,
  seed: ProjectDesignSeed,
  posture: CodePosture,
  designVersion: number,
): CodeSnapshot {
  const stages = Object.fromEntries(
    CODE_STAGE_IDS.map((id) => [
      id,
      {
        id,
        status: posture === "not-started" ? "pending" : "complete",
        generatedFromVersion: posture === "not-started" ? 0 : CODE_VERSION,
        generatedAt: posture === "not-started" ? null : stamp(id),
        summary: null,
        error: null,
      },
    ]),
  ) as CodeStages;

  if (posture === "not-started") {
    return {
      projectId,
      codeVersion: 0,
      designVersion,
      designBlocker: null,
      generatedFromDesignVersion: 0,
      stages,
      scope: null,
      nextSprint: null,
      techStack: null,
      contract: null,
      agreement: null,
      repository: null,
      diff: null,
      run: null,
      gate: { decision: null, history: [] },
      approvedThrough: null,
      thread: [],
    };
  }

  const contract = buildContract(seed, CODE_VERSION);
  const scope = buildScope(seed);
  const manifest = fileSet(contract, seed.appName);
  const called = new Set(
    contract.endpoints
      .filter((endpoint) => endpoint.traces.screenIds.length > 0)
      .map((e) => e.id),
  );
  const unused = contract.endpoints
    .filter((endpoint) => !called.has(endpoint.id))
    .map((e) => e.id);

  for (const id of CODE_STAGE_IDS) {
    stages[id].summary = summaryFor(
      id,
      contract,
      scope,
      manifest.length,
      unused.length,
    );
  }

  return {
    projectId,
    codeVersion: CODE_VERSION,
    designVersion,
    designBlocker: null,
    generatedFromDesignVersion: designVersion,
    stages,
    scope,
    nextSprint: null,
    techStack: buildStack(seed),
    contract: {
      version: CODE_VERSION,
      ruleArm: contract,
      llmArm: contract,
      llmFailure: null,
      chosen: "rule",
      contract,
      ruleFindings: [],
      comparison: {
        rule: {
          endpoints: contract.endpoints.length,
          errors: 0,
          warnings: 0,
          attempts: 1,
        },
        llm: {
          endpoints: contract.endpoints.length,
          errors: 0,
          warnings: unused.length,
          attempts: 1,
        },
        agreed: contract.endpoints.map(
          (endpoint) => `${endpoint.method} ${endpoint.path}`,
        ),
        ruleOnly: [],
        llmOnly: [],
        conflicts: [],
        agreementRate: 1,
      },
    },
    agreement: {
      contractVersion: CODE_VERSION,
      findings: unused.map((id) => ({
        ruleId: "endpoint-not-called",
        severity: "warning" as const,
        reason: `no generated page calls ${id}`,
        hint: `Either a screen should use ${id} or it exists for a non UI caller; the reader decides which.`,
        subject: id,
        location: null,
      })),
      counts: {
        endpointsTotal: contract.endpoints.length,
        endpointsImplemented: contract.endpoints.length,
        endpointsMissing: [],
        endpointsCalled: called.size,
        endpointsUnused: unused,
        orphanRoutes: [],
        foreignCalls: [],
        schemaMismatches: 0,
        agreementRate: 1,
      },
    },
    repository: {
      version: CODE_VERSION,
      manifest,
      build: {
        toolchain: "node 22.17.0 / npm 10.9.2",
        isolation:
          "A subprocess in a scrubbed temporary directory: only PATH, HOME and an npm cache reach the child, with time and output caps per step. Not a container, because Docker is not installed here, so kernel level isolation is not claimed.",
        steps: [
          {
            name: "install",
            command: "npm install --no-audit --no-fund",
            outcome: "passed",
            durationSeconds: 41.2,
            logTail: "added 214 packages in 41s",
          },
          {
            name: "typecheck",
            command: "npm run typecheck",
            outcome: "passed",
            durationSeconds: 6.8,
            logTail: "",
          },
          {
            name: "unit tests",
            command: "npm test",
            outcome: "passed",
            durationSeconds: 4.1,
            logTail: `Test Files 2 passed\\nTests ${contract.endpoints.length} passed`,
          },
        ],
      },
      repository: null,
      // The truth of a demo with no credentials in it. An invented URL would
      // be the one lie this phase most needs not to tell.
      notPushedReason:
        "not pushed: the project owner has no GitHub connection. Connect one in Settings and generate again.",
    },
    diff: null,
    run: null,
    gate:
      posture === "approved"
        ? {
            decision: {
              kind: "approved",
              at: stamp("code-review"),
              by: "Alex Chen",
              version: CODE_VERSION,
              note: null,
            },
            history: [],
          }
        : { decision: null, history: [] },
    approvedThrough: null,
    thread: threadFor(stages, posture),
  };
}

/**
 * The demo has no clock of its own, and the wall clock would make fixture
 * output differ every run. Timestamps advance from a seeded moment instead.
 */
function stamp(stageId: string): string {
  const index = Math.max(CODE_STAGE_IDS.indexOf(stageId as CodeStageId), 0);
  const base = Date.UTC(2026, 7, 14, 9, 0, 0);
  return new Date(base + index * 4 * 60_000).toISOString();
}

function summaryFor(
  id: CodeStageId,
  contract: ApiContract,
  scope: SprintScope,
  files: number,
  unused: number,
): string {
  const inScope = scope.stories.filter((story) => story.inScope);
  const screens = new Set(inScope.flatMap((story) => story.traces.screenIds));
  switch (id) {
    case "sprint-scope":
      return `Sprint scope proposed: ${inScope.length} ${inScope.length === 1 ? "story" : "stories"} across ${screens.size} screens`;
    case "tech-stack":
      return "Tech stack proposed: MERN";
    case "api-contract":
      return `API contract inferred: ${contract.endpoints.length} endpoints from the rule arm, arms agree on 100% of the union`;
    case "frontend-code":
      return `Frontend generated: ${screens.size} pages, typed client included`;
    case "backend-code":
      return `Backend generated: ${contract.entities.length} models with contract tests`;
    case "contract-agreement":
      return `Contract agreement checked: 100% implemented${unused ? `, ${unused} warnings to read` : ""}`;
    case "build":
      return `Build passed: install, typecheck and tests all green. ${files} files, not pushed: no GitHub connection`;
    case "code-review":
      return "Everything generated so far is waiting on your decision";
  }
}

function threadFor(
  stages: CodeStages,
  posture: CodePosture,
): CodeThreadMessage[] {
  const messages: CodeThreadMessage[] = CODE_STAGE_IDS.filter(
    (id) => id !== "code-review",
  ).map((id) => ({
    id: `code-thread-${id}`,
    kind: "stage_summary" as const,
    stageId: id,
    author: "Code agent",
    content: stages[id].summary ?? "",
    at: stages[id].generatedAt ?? stamp(id),
    producedVersion: null,
  }));
  if (posture === "approved") {
    messages.push({
      id: "code-thread-decision",
      kind: "system",
      stageId: "code-review",
      author: "Alex Chen",
      content: "Approved the code. Testing and Security can start.",
      at: stamp("code-review"),
      producedVersion: null,
    });
  }
  return messages;
}
