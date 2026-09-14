"""The supported stack catalog: small, honest about what exists.

Two entries. `mern` has working generators; `react-spring-postgres` is
declared, scored and shown, and says plainly that its generators are not
built yet, because a stack the platform cannot generate must never be
selectable into a build that would then be written by prose.
"""

from dataclasses import dataclass

from sdlc_contracts import StackLayer


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    layers: tuple[StackLayer, ...]
    available: bool
    unavailable_reason: str | None = None


CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="mern",
        name="MERN (TypeScript)",
        layers=(
            StackLayer(
                name="frontend",
                choice="React 19 + TypeScript + Vite",
                rationale="The platform's own frontend stack, so the generated app and its generator share one idiom.",
            ),
            StackLayer(
                name="backend",
                choice="Node + Express 5 + TypeScript",
                rationale="One language across the monorepo; the typed client and the handlers share the contract types.",
            ),
            StackLayer(
                name="database",
                choice="MongoDB (Mongoose), in memory repository for the sandbox build",
                rationale="Document shapes map straight onto the contract's entity models; the sandbox runs no database, and the build report says which repository ran.",
            ),
        ),
        available=True,
    ),
    CatalogEntry(
        id="react-spring-postgres",
        name="React + Spring Boot + PostgreSQL",
        layers=(
            StackLayer(
                name="frontend",
                choice="React 19 + TypeScript + Vite",
                rationale="The same frontend either way; the stacks differ behind the contract.",
            ),
            StackLayer(
                name="backend",
                choice="Spring Boot 3 + Java 21",
                rationale="Typed controllers and bean validation carry the contract's constraints into the runtime.",
            ),
            StackLayer(
                name="database",
                choice="PostgreSQL",
                rationale="Relational integrity for entity models that reference each other and writes that cross boundaries.",
            ),
        ),
        available=False,
        unavailable_reason=(
            "Generators for this stack are not built yet. They land before the "
            "testing component's Java work needs them; until then a build on "
            "this stack cannot be generated honestly."
        ),
    ),
)


def entry_for(stack_id: str) -> CatalogEntry:
    for entry in CATALOG:
        if entry.id == stack_id:
            return entry
    known = ", ".join(entry.id for entry in CATALOG)
    raise KeyError(f"{stack_id} is not in the stack catalog ({known})")
