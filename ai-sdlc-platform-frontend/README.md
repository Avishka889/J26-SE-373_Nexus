# SDLC AI — Intelligent Software Development Lifecycle Platform

React SPA for an AI-assisted end-to-end SDLC pipeline (requirements → code → testing → deployment) with continuous traceability.

> **Status:** Structure migrated to feature folders; runtime seams (Query, HTTP, fixtures-behind-API) are in place for the reference path. See [FRONTEND_STRUCTURE.md](./FRONTEND_STRUCTURE.md) for the source of truth. This README previously described a deleted `pages/` / `components/` layout — ignore older copies.

## Quick Start

```bash
npm install
npm run dev      # http://localhost:5173
npm run build
npm run lint
npm test         # Vitest unit tests
npm run e2e      # Playwright (starts Vite automatically)
```

`npm run dev` reads every feature from the orchestrator at `VITE_API_URL` (set in `.env.development`). Fixtures are unwired from the running app and kept for the tests; to run the demo on them, with no backend:

```bash
npm run dev -- --mode fixtures
```

`.env.example` explains each variable.

## Architecture

| Layer | Role |
|-------|------|
| `src/app/` | Composition root: routes, providers, guards, shells |
| `src/features/` | One folder per product capability / backend service |
| `src/entities/` | Shared domain clients (projects, settings, pipeline) |
| `src/shared/` | Cross-feature UI (no product store imports) |
| `src/lib/` | HTTP, env, QueryClient, logging |
| `src/store/` | Zustand **session + UI only** |
| `src/types/` | Contract / domain DTO re-exports |

**Stack:** React 19, Vite, TypeScript, Tailwind 4, React Router 7, Zustand (UI/session), TanStack Query (server/cache), fixtures inside each feature's api module, read only in the fixture modes (`--mode fixtures`, Playwright, vitest).

Layer rule: `app → features → shared / lib / types / store / entities`. Features do not import other features (use relative imports inside a feature).

## Feature slots

Each feature follows: `api/` · `hooks/` · `model/` · `components/` · `fixtures/` · thin `page.tsx` · `index.ts`.

Reference implementation: `src/features/deployment/`.

## Scripts

| Script | Purpose |
|--------|---------|
| `dev` / `build` / `preview` | Vite |
| `lint` | ESLint with layer boundary rules |
| `test` / `test:watch` | Vitest (`src/**/*.test.ts`) |
| `e2e` / `e2e:ui` | Playwright critical journeys |

## Components (product)

1. **Requirements & Design (C1)** — ingestion, SAG, UML, wireframes, sprint plan  
2. **Code Generation (C2)** — contracts, frontend/backend studios, build validation  
3. **Testing & Security (C3)** — suites, healing, quality, security, re-verify, report  
4. **Deployment & Dependency (C4)** — repos, deps, release pipeline, verify  

Plus marketing landing, auth, projects home, settings integrations, and activity/traceability log.

## Design tokens

Phase colors: C1 blue, C2 indigo, C3 violet, C4 amber — see `src/index.css` and `FRONTEND_STRUCTURE.md`.
