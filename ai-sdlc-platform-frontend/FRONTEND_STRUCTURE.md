# Frontend Structure (finalized)

Companion to the monorepo architecture docs. This file is the source of truth for the
shape of this React SPA so it stays workable as the four component services come online
and the orchestrator replaces fixtures.

Two goals drive every decision here:

1. **The backend swap must be a deletion, not a rewrite.** When `/api/runs` exists, we
   should be turning fixtures off, not editing components.
2. **The frontend must mirror the system it drives.** A folder per component service, so
   `features/testing` ↔ `services/c3-testing-security` ↔ `validation-report.schema.json`
   line up by name. A new team member finds the code by knowing the architecture.

---

## Stack decisions (locked)

| Concern | Choice |
|---------|--------|
| Runtime | React 19 + TypeScript + Vite SPA (no Next.js unless SSR/SEO becomes required) |
| Server / cache state | TanStack Query |
| UI / session state | Zustand only (theme, sidebar, toasts, auth flags) |
| Fixtures | Inside each feature's api module, read only in the fixture modes (`--mode fixtures`, Playwright, vitest); development and production builds read only the backend |
| Boundaries | ESLint `no-restricted-paths` / `eslint-plugin-boundaries` |
| Packaging | Single app until a second deployable FE exists (then consider Nx/Turborepo) |

---

## Target tree

```
ai-sdlc-platform-frontend/
├── .env.example
├── .env.local                     # gitignored
├── index.html
├── vite.config.ts
├── tsconfig.json
├── eslint.config.js               # boundary + security rules
├── vitest.config.ts
├── playwright.config.ts
├── public/
├── e2e/                           # Playwright: critical journeys only
│   ├── auth.spec.ts
│   └── project-pipeline.spec.ts
└── src/
    ├── main.tsx                   # bootstrap only
    ├── index.css
    ├── vite-env.d.ts
    │
    ├── app/                       # composition root — only layer that knows all features
    │   ├── App.tsx
    │   ├── routes.tsx             # ALL routes (no nested <Routes> in pages)
    │   ├── providers.tsx          # QueryClient, Router, Theme, Toasts, ErrorBoundary
    │   ├── guards/
    │   │   ├── AuthGuard.tsx
    │   │   └── ProjectGuard.tsx
    │   ├── errors/
    │   │   ├── ErrorBoundary.tsx
    │   │   └── RouteError.tsx
    │   └── layout/
    │       ├── AppShell.tsx
    │       ├── ProjectShell.tsx
    │       ├── Sidebar.tsx
    │       ├── TopBar.tsx
    │       ├── AccountMenu.tsx
    │       └── CommandPalette.tsx
    │
    ├── features/                  # one folder ↔ one product capability / backend service
    │   ├── auth/
    │   ├── marketing/             # landing
    │   ├── projects/
    │   ├── requirements/          # C1
    │   ├── code-generation/       # C2
    │   ├── testing/               # C3
    │   ├── deployment/            # C4
    │   ├── activity/              # traceability / audit
    │   └── settings/              # integrations (git, vercel, azure, db, ai)
    │       ├── api/               # thin HTTP / fixture seam (may re-export entities)
    │       ├── components/        # feature UI (and feature-internal shared widgets)
    │       ├── pages/             # optional: multi-route features (see projects/)
    │       ├── hooks/             # may thin-wrap @/entities/* for feature DX
    │       ├── model/             # pure, unit-testable, no JSX
    │       ├── fixtures/          # MSW handlers + demo payloads for THIS feature
    │       ├── page.tsx           # thin composition (default export = lazy route entry)
    │       ├── msw.ts             # optional MSW entry (not part of page barrel)
    │       └── index.ts           # public API: default page + named exports
    │
    ├── entities/                  # cross-feature domain clients (project, settings, pipeline)
    │   ├── project/               # projectsApi + useProject / useProjectsList
    │   ├── settings/              # settingsApi + useSettings
    │   └── requirements/          # requirements pipeline store
    │       # Feature hooks/api often re-export these — look here for real domain logic
    │
    ├── shared/                    # used by 2+ features; no product ownership
    │   ├── ui/                    # primitives, surface tokens, Field, GlassCard, composer chrome, brand/
    │   ├── code-viewer/           # VSCodeEditor, file tree, syntax
    │   ├── viz/                   # lazy Mermaid (React Flow stays feature-owned until 2+ consumers)
    │   ├── theme/                 # ThemeProvider + useTheme bridge (Zustand stays in store/)
    │   ├── model/                 # pure domain helpers used by 2+ features (none today)
    │   ├── hooks/                 # cross-feature hooks (useEditorTabs, …)
    │   ├── utils/                 # cn()
    │   └── constants/             # font / design tokens (not phase enums — those live in CSS/features)
    │
    ├── lib/                       # infrastructure — zero product knowledge
    │   ├── http.ts                # sole fetch entry: base URL, auth, timeouts, typed errors
    │   ├── query.ts               # QueryClient + key factories
    │   ├── env.ts                 # typed import.meta.env; fail loud on missing
    │   ├── storage.ts             # safe localStorage wrapper (no secrets)
    │   ├── logger.ts              # structured client logging (no PII)
    │   └── telemetry.ts           # optional analytics / error reporting hooks
    │
    ├── store/                     # Zustand UI/session ONLY — never server entity caches
    │   ├── index.ts
    │   ├── session.ts             # auth flags, active project id (not tokens in plain text)
    │   └── ui.ts                  # theme, sidebar, toasts, command palette
    │
    ├── types/                     # re-exports of contract types + UI-only view models
    │   ├── contracts.ts
    │   └── ui.ts
    │
    └── assets/                    # static images/fonts referenced by shared/app
```

---

## Layer rules (enforce, don't document-only)

```
app  →  features  →  shared / lib / types / store / entities
                    shared → lib / types / assets
                    store  → lib
                    entities → lib / types / store (toasts only via getState when needed)
```

| Rule | Why |
|------|-----|
| `app` may import anything | Composition root |
| `app` imports features **only** via `@/features/<name>` | Stable public surface (no deep hooks/fixtures paths) |
| A feature **never** imports another feature | Prevents tangled domains and duplicate panels |
| Import a feature **only** through its `index.ts` | Stable public surface |
| Import shared via **area barrels** (`@/shared/ui`, `@/shared/hooks`, …) | Stable design-system surface; prefer barrels for new code |
| `shared/` and `lib/` never import a feature | Keeps infrastructure reusable |
| Cross-feature domain state lives in `entities/` | Features thin-wrap entities in `api/` / `hooks/` when needed |
| No product pipeline math in `shared/ui` | Domain helpers live in `shared/model` (or feature `model/`) |
| Theme state stays in `store/ui`; shared reads via `shared/theme` | No Zustand imports inside shared |
| Heavy phase routes use `React.lazy(() => import("@/features/<name>"))` | Feature `index` default-exports the page for clean code-splitting |
| Multi-route features use `pages/` + `components/` | e.g. `projects/pages/{Home,Projects,NewProject}` vs shared `ProjectCreatePrompt` |
| Thin `hooks/`/`api/` re-exports of `entities/` are OK | Domain logic lives in `entities/`; feature folders stay the DX door |
| No raw `fetch` outside `lib/http.ts` | One place for auth headers, CSRF, error normalization |
| No secrets in Zustand `persist` | Tokens/API keys must not land in localStorage |

Cross-feature needs go through `app/` (compose both) or move the piece into `shared/` when **2+ consumers** exist.
If two features genuinely need the same panel, it moves to `shared/`.

Encode these with ESLint `no-restricted-imports` and `.github/CODEOWNERS` on `src/shared/**`
so CI / review fails on violations rather than relying on memory.

---

## Security conventions

1. **`lib/http.ts`** — attach Bearer/session headers; strip tokens from error logs;
   normalize 401 → session clear + redirect.
2. **`store/session.ts`** — persist only non-sensitive session flags (e.g.
   `isAuthenticated`, user display name). Integration secrets in Settings stay in
   memory or a backend vault; never `persist` API keys/tokens.
3. **`app/guards/`** — auth and project-scoped route protection live outside feature pages.
4. **`lib/env.ts`** — only `VITE_*` public config; no private keys in the client bundle.
5. **Fixtures via MSW** — components always call real `api/` modules; never import
   fixture blobs into UI (avoids shipping demo payloads to production when gated).
6. **CSP / headers** — document expected headers in deploy (`vercel.json`); the folder
   structure itself does not bypass this.

---

## Server vs client state

| Kind | Home |
|------|------|
| Runs, reports, SAG, test results, deployments | TanStack Query in `features/*/hooks` |
| Theme, sidebar, toasts, active project id | `store/` |
| Auth gate + redirects | `app/guards` + `store/session` |
| Demo data | `features/*/fixtures` (MSW), not a global `data/mockData.ts` |

### Backend seam

1. **Types come from contracts**, never hand-written twice. Prefer generated
   `@sdlc/contracts-ts` (or equivalent); `src/types/` re-exports plus UI-only types.
2. **One HTTP module.** Every feature `api/` is thin:

   ```ts
   // features/testing/api/runs.ts
   import { http } from "@/lib/http";
   import type { ValidationReport } from "@/types/contracts";

   export const getValidationReport = (runId: string) =>
     http.get<ValidationReport>(`/runs/${runId}/validation`);
   ```

3. **Fixtures live behind the network boundary.** Each feature's `api/` module
   answers from its fixtures or from the backend, chosen by `liveFeaturesFor`.
   MSW handlers were used at first and removed on 2026-08-10; since 2026-10-03
   development and production builds read only the backend, and fixtures answer
   only in the fixture modes.
4. **Environment** (read once via `lib/env.ts`):

   ```
   VITE_API_URL=http://localhost:8000
   VITE_LIVE_FEATURES=   # read only in the fixture modes; see .env.example
   ```

---

## Feature internal shape

Every feature follows the same slots:

| Slot | Role |
|------|------|
| `api/` | Thin typed HTTP calls |
| `model/` | Pure derivations (progress, gate states, counts) + colocated `*.test.ts` |
| `components/` | UI panels/steps |
| `hooks/` | Query/mutations wired to `api/` |
| `fixtures/` | MSW handlers + demo payloads for this feature |
| `page.tsx` | Compose only; target under ~200 lines |
| `index.ts` | Public door — page + types needed by `app/routes` |

---

## Where does it go?

| Adding | Goes in |
|--------|---------|
| A new screen for a component service | `features/<service>/components/` |
| A number derived from run data | `features/<service>/model/` (pure, tested) |
| A call to the orchestrator | `features/<service>/api/` |
| A button/badge/table/surface token used twice | `shared/ui/` (`surface`, `Field`, `GlassCard`, composer chrome) |
| A wrapper around a heavy library | `shared/viz/` (lazy loaded) |
| Demo data for one feature | `features/<service>/fixtures/` |
| Auth, theme, sidebar state | `store/` |
| A route | `app/routes.tsx` |
| Route protection | `app/guards/` |

---

## Conventions

- **One router.** All routes in `app/routes.tsx`, including nested project routes. Never a
  `<Routes>` inside a page component, and never a relative `<Navigate>` in a splat route.
- **Page files stay thin.** A `page.tsx` composes; it does not hold panels. If a file
  passes ~300 lines, a panel wants extracting.
- **Model logic is pure.** Anything computing counts, states or progress lives in
  `model/` with no JSX, so it can be unit tested without rendering.
- **Colocate tests:** `model/view.test.ts` beside `model/view.ts`.
- **Naming:** `PascalCase.tsx` for components, `camelCase.ts` for everything else,
  folders `kebab-case`.
- **Heavy libraries are lazy.** Graph, chart and diagram libraries load with the route
  that needs them (`React.lazy` + `Suspense`), never on first paint.
- **Query key factories** live in `lib/query.ts` (e.g. `runKeys.detail(id)`) so
  invalidation stays consistent.

---

## Migration map from the current repo

| Today | Target |
|-------|--------|
| `pages/ProjectWorkspace.tsx` (routes + shell + sections) | `app/routes.tsx` + `app/layout/ProjectShell.tsx` + `features/requirements/*` |
| `pages/TestingSecurity.tsx` + `components/testing/*` | `features/testing/` |
| `pages/CodeGeneration.tsx` + `components/code/*` (viewer) | `features/code-generation/` + `shared/code-viewer/` |
| `pages/DeploymentDependency.tsx` | `features/deployment/` |
| `pages/ActivityLog.tsx`, `pages/Traceability.tsx` | `features/activity/` |
| `pages/Projects.tsx`, `pages/NewProject.tsx`, `pages/Home.tsx` | `features/projects/` |
| `pages/Landing.tsx`, `pages/Login.tsx` | `features/marketing/`, `features/auth/` |
| `pages/Settings.tsx` | `features/settings/` |
| `data/mockData.ts` and related fixtures | split into each feature's `fixtures/` |
| `components/ui/*` | `shared/ui/` |
| `components/layout/*`, `components/brand/*` | `app/layout/`, `shared/ui/brand/` |
| `components/sag/*`, Mermaid, Recharts usage | `shared/viz/` (lazy) |
| `store/useStore.ts` | `store/session.ts` + `store/ui.ts` |
| `utils/cn.ts` | `shared/utils/cn.ts` |
| `App.tsx` at `src/` | `app/App.tsx` |

Migrate **one feature at a time**. Do not big-bang move the tree while routes still live
in page components.

### Deliberately not repeating

1. **A shared data bag.** `data/mockData.ts` served every phase; removing one export
   broke an unrelated feature. Fixtures belong to a feature.
2. **Two implementations of one feature.** A single `index.ts` door makes accidental
   duplicates hard.
3. **Routing in two files.** One router, absolute redirect targets.
4. **Global CSS hiding layout bugs.** Fix layouts; keep overflow checks as tests.

---

## Migration status

**Structure migrated; runtime seams in progress (~70%).** Runtime boots
`src/main.tsx` → `src/app/App.tsx` → `app/routes.tsx`. Legacy `src/pages`,
`src/components`, `src/data`, `src/utils`, and `src/App.tsx` have been removed.

Zustand is **session + UI only** (`store/session.ts`, `store/ui.ts`). Project /
settings / pipeline entity state lives in `src/entities/*` with feature `api/`
seams. TanStack Query, MSW, ESLint, Vitest, and Playwright are installed.
Feature pages are thin compositions; fixtures are consumed via `api/` (not
direct UI imports for testing/deployment/activity).

### Remaining residuals

| Item | Reason |
|------|--------|
| Generated `@sdlc/contracts-ts` | Placeholder DTOs in `types/contracts.ts` until schemas are published |
| Full MSW coverage for every feature | Testing handlers exist; expand per feature as HTTP paths stabilize |
| CI gate for ESLint boundaries | Config ready; wire in pipeline when repo CI exists |
| Real auth tokens | Demo login sets session flags only; `lib/http` Bearer helper is ready |

---

## Seed checklist

- [x] Document finalized tree, layer rules, security, migration map
- [x] Full target tree + feature migration (no legacy pages/components/data)
- [x] `eslint.config.js`, `vitest.config.ts`, `playwright.config.ts`, `.env.example`
- [x] Retire god `useStore`; session/ui live; entities + Query providers
- [x] Install TanStack Query, MSW, ESLint, Vitest, Playwright
- [x] Thin pages + fixture→API seams (deployment, testing, activity, projects, settings)
- [x] Unit tests for pure model modules; Playwright smoke specs authored
- [ ] Enforce ESLint boundaries in CI
- [ ] Generate contract types into `types/contracts.ts` (or `@sdlc/contracts-ts`)
- [ ] Expand MSW handlers for all features; run e2e in CI
