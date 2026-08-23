# AI-Driven Autonomous Software Development Lifecycle (SDLC) Framework

Research group: AIMS. Specialization: Software Engineering (SLIIT).

An end-to-end framework that turns natural-language requirements into a tested, secured, deployed and continuously maintained software system through four integrated engines. Every engine pairs a deterministic rule-based layer (trust, audit) with an agentic AI layer (reasoning); Component 3 adds a trained ML model; every automated change passes a human approval gate; the whole thing runs inside an agile/DevOps loop.

## Components
| # | Engine | Core novelty |
|---|---|---|
| C1 | Requirement Engineering, Architecture & Design | Semantic Architecture Graph reused to generate architecture, UML and wireframes with traceability |
| C2 | Wireframe-to-Code Generation | Requirement-aware contract-first generation of both frontend and backend; rule-vs-LLM comparison |
| C3 | Testing & Security Validation | Honesty-guarded self-healing tests; trained-model vs LLM vs combined security detection |
| C4 | Deployment & Dependency Evolution  Pre-update, client-specific breaking-change prediction with risk levels and rollback planning |

## Architecture and stack
Modular, service-oriented (not a monolith, not microservices): four coarse-grained component services + a thin orchestrator + a React web console, in a monorepo, run with docker-compose. Components talk through versioned JSON-Schema artefact contracts, so they develop in parallel and integrate at defined milestones.

- Frontend: React 19 + TypeScript + Vite 8 + Tailwind CSS v4 + React Router 7 + Radix + @xyflow/react
- Backend services + orchestrator: Python + FastAPI + Pydantic
- Data: PostgreSQL (JSONB artefacts + audit log)
- LLMs: Claude Sonnet 4.6 (workhorse), Opus 4.8 / Gemini 3.1 Pro (hard/long-context), a hosted-free open model (Groq); one trained C3 model (CodeBERT/GraphCodeBERT or XGBoost) on free cloud GPU
- Deploy: GitHub + GitHub Actions + Docker; the framework also generates Kubernetes manifests

See `PROJECT_STRUCTURE.md` for the full folder layout and `docs/` for the plan, novelty packages, datasets/LLM plan, architecture and TAF.

## Running it locally

Two processes: the orchestrator (FastAPI, port 8000) and the web console (Vite,
port 5173). Start them in two terminals and stop them with Ctrl-C.

### Once, before the first run

```bash
# Python: one uv workspace, one lock, one virtualenv for all three members.
uv sync --all-extras

# Configuration. Fill in the database URLs and ANTHROPIC_API_KEY.
cp .env.example .env

# Database schema. Reads DATABASE_URL from .env.
cd orchestrator && uv run alembic upgrade head && cd ..

# Frontend packages.
cd ai-sdlc-platform-frontend && npm install && cd ..
```

`.env` lives at the repository root, is gitignored, and is read directly by the
orchestrator. Nothing needs exporting: `uv run uvicorn ...` picks it up, including
the provider key. A missing key stops the server at startup with a message rather
than failing every stage once a run is under way.

#### `C1_MODE`: where Component 1 runs

`C1_MODE` decides how the orchestrator reaches Component 1, not which model it
uses. `inprocess` imports C1 and runs it inside the orchestrator process, which is
the development default and what pytest uses. `http` calls the separately running
service at `C1_BASE_URL`, which is the compose and production path. The service
boundary is real either way, so this changes deployment rather than architecture.

Only `inprocess` needs a provider key in this `.env`, because under `http` the key
belongs to the C1 service instead.

#### `C1_MODEL`: which provider answers

The prefix of `C1_MODEL` is the only thing that chooses a provider. Having both
keys set is the normal state rather than an ambiguity: the prefix names one
provider, the orchestrator reads that provider's key, and the other key is never
consulted.

    C1_MODEL=anthropic:claude-sonnet-5      reads ANTHROPIC_API_KEY
    C1_MODEL=anthropic:claude-haiku-4-5     reads ANTHROPIC_API_KEY
    C1_MODEL=google:<a gemini model>        reads GOOGLE_API_KEY
    C1_MODEL=openrouter:<vendor>/<model>    reads OPENROUTER_API_KEY
    C1_MODEL=groq:<a model>                 reads GROQ_API_KEY

Anthropic runs production. Google and OpenRouter carry the development loop on
their free tiers, and OpenRouter's one key reaches many vendors, so trying a
different model there costs nothing but the line.

Presence never decides. A filled in `GROQ_API_KEY` cannot answer for a missing
`ANTHROPIC_API_KEY`: the server refuses to start and names the variable it wanted.
That refusal is the point, because the alternative is a comparison run that
quietly produced its design on the other provider.

Changing that line takes a restart: the C1 client is built once while the process
starts, so editing `.env` reaches nothing until uvicorn is stopped and started
again.

Groq stays installed and selectable, but as of 2026-08-17 it serves nothing this
component can use. `llama-3.3-70b-versatile` was decommissioned and returns 404;
the `gpt-oss` models cap the free tier at 8000 tokens a minute while one C1
request needs about 11600, so no amount of pacing helps; `groq/compound` answers
`tool calling is not supported with this model`; and qwen cannot hold the
requirements schema. Use `claude-haiku-4-5` for the cheap lane instead: a third
of Sonnet's price on a provider whose tool calling this component already
depends on.

### Adding a fifth provider

Three one-line additions and nothing else: the extra in
`services/c1-requirements-design/pyproject.toml`, a `<name>_api_key` field on
`Settings`, and an entry in `PROVIDER_KEYS`. The field name has to be the
lowercase of the variable, because that is how `resolve_provider_key` finds it,
and a test asserts every wired provider has one. Miss the `PROVIDER_KEYS` entry
and the orchestrator refuses to start, naming the providers that do work.

A provider outside pydantic-ai's own list (NVIDIA NIM, for instance) cannot be
named by a model string at all and needs real code: a factory turning a prefix
into a model constructed with a custom base URL.

### Before wiring a new provider, ask it in one call

```bash
cd services/c1-requirements-design
uv run python -m c1.probe anthropic:claude-haiku-4-5
```

One request, using C1's real graph agent and its real rule catalogue, answering
the only question that matters: can this provider fill a nested schema under a
forced tool call. It reports SUITABLE, WORKABLE or UNUSABLE, and for a failure it
says which of the four mechanisms it was, because they are indistinguishable at a
glance and each one otherwise costs a whole run to identify.

### Terminal 1: the orchestrator

```bash
cd orchestrator
uv run uvicorn orchestrator.main:app --port 8000 --reload
```

Check it with `curl localhost:8000/health`.

### Terminal 2: the web console

```bash
cd ai-sdlc-platform-frontend
npm run dev            # http://localhost:5173
```

**Use port 5173.** The orchestrator only allows that origin through CORS
(`CORS_ORIGINS` in `.env`). On any other port the browser preflight is refused
with a 400 and the page fails silently, which looks like the app being broken.
If Vite says "Port 5173 is in use, trying another one", stop whatever is holding
it rather than accepting 5174: see "Stopping them" below.

### Which data the console reads

`VITE_LIVE_FEATURES` in `ai-sdlc-platform-frontend/.env.development` decides,
one feature at a time. It is committed, and the diff on that line is the record
of how much of the product is real.

```
VITE_LIVE_FEATURES=projects,requirements,activity
```

Live now: projects, requirements and activity, from the orchestrator. Still
fixtures: settings, testing, code-generation. An unknown name stops the dev
server and fails the build, on purpose, because a typo here would otherwise give
a demo that looks right and is not.

To run the whole product on demo fixtures, with no orchestrator at all:

```bash
npm run dev -- --mode fixtures      # reads .env.fixtures, everything mocked
```

Attaching a requirements document accepts PDF, DOCX, TXT and MD; every format is capped
at 10 MB and read up to 40,000 characters, with the attachment's chip stating how much
was skipped. TXT and MD are read in the browser itself, so they work with no orchestrator
running and the fixtures demo above keeps its upload.

### Stopping them

Ctrl-C in each terminal. If a server was backgrounded and is still holding a
port:

```bash
# What is listening
ss -ltnp | grep -E ':(5173|8000)'

# Stop it
pkill -f "uvicorn orchestrator"
pkill -f "vite"
```

### Tests

```bash
uv run pytest                       # every Python test, offline, no model calls
cd ai-sdlc-platform-frontend
npm test                            # frontend unit tests
npx playwright test                 # browser checks, on fixtures, offline
```

Nothing above reaches a provider: `ALLOW_MODEL_REQUESTS` is off by default in
both Python suites, so a forgotten override fails loudly instead of spending
money. The tests that do use a real model are marked and skipped unless asked
for:

```bash
uv run pytest -m live               # needs the provider key, spends tokens
```

The end-to-end walk through of the design phase against a real model needs both
servers running and is opt-in:

```bash
LIVE_DESIGN=1 npx playwright test --config playwright.live.config.ts
```

## Datasets
Public benchmarks only. Facts verified from official sources; full detail and caveats in `docs/Datasets_and_LLM_Plan`. Large data is gitignored; use download scripts under `datasets/`.

### Component 3 - security model training (Java-deep)
| Dataset | What | Get it |
|---|---|---|
| CWE-Bench-Java | 120 real Java CVEs, 4 CWE types (whole-repo eval) | https://github.com/iris-sast/cwe-bench-java |
| Juliet Java v1.3 (NIST SARD) | 28,881 synthetic Java cases, 112 CWEs (training) | https://samate.nist.gov/SARD/test-suites/111 |
| Vul4J | 79 reproducible Java vulns, 25 CWEs | https://github.com/tuhh-softsec/vul4j |
| InjectionVul4J | 123 Java injection vulns with patches | https://github.com/InjectionVul4J/InjectionVul4J |
| OWASP Benchmark (Java) | 2,740 runnable single-vuln servlets (TP/FP scoring) | https://github.com/OWASP-Benchmark/BenchmarkJava |
| OWASP WebGoat | deliberately vulnerable Spring Boot app (live demo target) | https://github.com/WebGoat/WebGoat |

### Component 3 - MERN / JavaScript security (no CWE-labeled benchmark exists; build small + use scanners)
| Dataset | What | Get it |
|---|---|---|
| SecBench.js | 600 real server-side JS vulns with exploits (5 classes; map to CWE; no license) | https://github.com/cristianstaicu/SecBench.js |
| CVEfixes | CWE-labeled multi-language vuln-fix commits (filter the JS/TS slice) | https://zenodo.org/records/13118970 |

### Component 3 - testing (generation, self-healing, mutation)
| Dataset | What | Get it |
|---|---|---|
| Defects4J | 854 real Java bugs | https://github.com/rjust/defects4j |
| GitBug-Java | 199 recent (2023) Java bugs | https://github.com/gitbugactions/gitbug-java |
| Methods2Test | 780,944 focal-method to test pairs | https://github.com/microsoft/methods2test |

### Other components (brief)
- C1: PURE (https://zenodo.org/records/7118517), PROMISE NFR, ModelSet (https://modelset.github.io/). No requirements-to-UML benchmark exists: build a small one.
- C2: WebCode2M (https://huggingface.co/datasets/xcodemind/webcode2m), Design2Code (https://github.com/NoviScl/Design2Code), APIs.guru specs (https://github.com/APIs-guru/openapi-directory), AutoRestTest services. No wireframe-plus-requirements to contract benchmark exists: build it (this is C2's novelty gap).
- C4: BUMP (https://github.com/chains-project/bump, 571 Maven positives; build negatives). No npm breaking-update benchmark exists: build a small npm set.

The security model trains on free cloud GPU (Google Colab T4 or Kaggle), not the project laptop; inference runs locally.

## Testing and where Component 3 writes tests
Component 3 does not test the orchestration console (the React app in `frontend/`). It generates and validates tests for the **target applications the framework builds**, that is, Component 2's output. The generated test code lives in the **same repository that Component 2 created**, next to the application code (both stacks), is executed there by the C3 harness, and is what the self-healing loop repairs.

- Backend (Java / Spring Boot): JUnit5 unit / integration / API tests, JaCoCo coverage, PIT mutation, SpotBugs / CodeQL / Semgrep. The honesty-guarded self-healing and the trained security model live here, because the honesty guard is a unit-test mechanism (it relies on mutation testing).
- Frontend (MERN / React): Jest + React Testing Library, nyc coverage, StrykerJS mutation, npm-audit / ESLint-security / Semgrep.
- API and integration: generated from Component 2's OpenAPI contract, on both stacks.
- Playwright: optional / stretch, not a core pillar. It is browser end-to-end automation, a different layer from the unit/integration/API + security + self-healing pillars. If wanted, it fits the MERN target app and is a natural place to demonstrate self-healing on UI locators (the industrial analog, Mabl and Testim), complementing the mutation-guarded self-healing on JUnit unit tests. Keep it optional to avoid scope creep; the core self-healing and honesty guard stay on JUnit.

## Process flow
See `Process_Flow.md` for the end-to-end flow diagram (Mermaid), including the approval gates and the self-healing, fix-and-re-verify, and maintenance-feedback iteration loops.

## Academic milestones 
Charter (done) -> Proposal (12%) -> Progress Presentation I (15%) -> Progress Presentation II (18%) -> Final Presentation & VIVA (20%) + Final Report (19%) + published Research Paper (10%) + Website (2%) + logbook/status (4%). Full phase-by-phase plan in `docs/Project_Plan`.

## Team and academic note
SLIIT, Faculty of Computing, final-year BSc (Hons) Software Engineering. This is an academic research project; all datasets and tools are public, and no plagiarism is permitted.
