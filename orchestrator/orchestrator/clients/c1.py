"""How the orchestrator reaches Component 1.

One protocol, two implementations, chosen by configuration. In process imports
the component and calls it directly, which is the development default and what
pytest uses. Over HTTP it posts to the running service, which is the compose
path. The boundary is the same either way: the six stage calls carry the same
generated contract types on the wire in either mode, and `name_project`
carries a plain string in both, since it produces no artefact for a type to
describe. Nothing in the orchestrator knows how a requirement is read or a
graph is built.

That is what makes the choice deployment rather than architecture. Splitting the
component into its own process later is a configuration change, and keeping it
in one process today costs no fidelity, because the seam is already here and both
sides of it are exercised.

The component's own result type is not used here. In HTTP mode the orchestrator
must not import the component at all, so the shape that crosses the boundary is
defined on this side and the in process adapter converts into it.
"""

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from sdlc_contracts import (
    ArchitectureGraph,
    ArchitectureRecommendation,
    ParsedRequirement,
    RequirementsArtefact,
    SprintPlan,
    UmlArtefact,
    WireframesArtefact,
)

from .thinking import Levelled, thinking_sent


@dataclass(frozen=True)
class StageOutcome[T]:
    """What one stage produced, as the orchestrator receives it."""

    artefact: T
    #: The one line posted into the thread when the stage finishes.
    summary: str
    #: Honesty metrics, recorded in the audit log rather than in the artefact.
    notes: dict[str, Any] = field(default_factory=dict)


class C1Client(Protocol):
    """The six stage calls Component 1 answers, plus a seventh that is not one.

    Per stage rather than one call, because each one is a stage the reader
    watches move from generating to complete, and because a crash should cost
    the stage that was running rather than the whole run. `name_project` is the
    exception: no artefact is stored and no stage row moves, so it answers with a
    bare title instead of a `StageOutcome`. It is not off the critical path,
    though: the run cannot start its first stage until it returns, which is why
    the runner bounds it rather than letting it inherit a stage's patience.
    """

    #: What actually produced the artefacts, for the record on a run.
    #:
    #: Read from the client rather than from settings, because the client is
    #: built once when the process starts: settings edited afterwards describe a
    #: run that has not happened yet. Telling those apart cost real time.
    model: str

    async def parse_requirements(self, text: str) -> StageOutcome[RequirementsArtefact]: ...

    async def build_graph(
        self, requirements: list[ParsedRequirement], *, text: str
    ) -> StageOutcome[ArchitectureGraph]: ...

    async def recommend(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageOutcome[ArchitectureRecommendation]: ...

    async def write_uml(self, graph: ArchitectureGraph) -> StageOutcome[UmlArtefact]: ...

    async def draw_wireframes(
        self,
        graph: ArchitectureGraph,
        *,
        requirement_ids: list[str],
        version: str,
        requirements: list[ParsedRequirement] | None = None,
    ) -> StageOutcome[WireframesArtefact]: ...

    async def plan_sprint(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageOutcome[SprintPlan]: ...

    #: Not a stage: no artefact and no stage row, and a failure costs a name
    #: rather than a run. The run does wait on it, and neither implementation
    #: below bounds it usefully, so the caller does.
    async def name_project(self, text: str) -> str: ...


#: How long one in-process design stage may take before it is stopped. The
#: component's provider client waits up to ten minutes for a single request and
#: then retries it, so one hung request held a stage, and the run behind it, for
#: half an hour with nothing to cancel it. Twice the HTTP client's limit
#: (`STAGE_TIMEOUT_SECONDS`): in process there is no service between the run and
#: the model to give up first, and a slow stage is not a failed one.
IN_PROCESS_STAGE_SECONDS = 600.0


async def _within[T](call: Awaitable[T]) -> T:
    """A stage call held to its time limit, ending in words a reader can act on."""
    try:
        async with asyncio.timeout(IN_PROCESS_STAGE_SECONDS) as limit:
            return await call
    except TimeoutError:
        if not limit.expired():
            raise
        raise TimeoutError(
            f"the stage took longer than {IN_PROCESS_STAGE_SECONDS / 60:.0f} minutes, "
            "so it was stopped. Try it again"
        ) from None


class InProcessC1:
    """The component, imported and called directly.

    The import is deferred to construction rather than done at module load, so
    an orchestrator deployed to talk to C1 over HTTP does not need the
    component's dependencies installed to start.
    """

    def __init__(self, model: Any, *, thinking: str = "off") -> None:
        try:
            from c1.agents import settings_for
            from c1.service import C1
        except ModuleNotFoundError as exc:  # pragma: no cover - deployment shape
            raise RuntimeError(
                "C1_MODE is 'inprocess' but the component is not installed. "
                "Install the sdlc-c1 package, or set C1_MODE=http and C1_BASE_URL."
            ) from exc
        # One component per thinking level: the configured one now, any other
        # when a run that chose it first asks (3B).
        self._levels = Levelled(lambda level: C1(model, thinking=level), thinking, opens=True)
        self._model = model
        self._settings_for = settings_for
        # `model` is a string in every real deployment and a built model object
        # in tests, so `str` rather than assuming.
        self.model = str(model)
        #: The configured level, which a run uses where its account chose none.
        self.level = thinking
        # Read from the settings every agent is built with, so a run records
        # what its requests say about thinking rather than what was assumed.
        self.thinking = self.thinking_for(thinking)

    @property
    def _c1(self) -> Any:
        """The component at the configured level."""
        return self._levels.configured

    def thinking_for(self, level: str) -> str:
        """What this component's requests say about thinking at a level, as a run records it."""
        return thinking_sent(self._settings_for(self._model, thinking=level))

    async def __aenter__(self) -> "InProcessC1":
        """Open the components' provider connections, so shutdown can close them."""
        await self._levels.open()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._levels.close(*args)

    @staticmethod
    def _as_outcome(result: Any) -> StageOutcome[Any]:
        return StageOutcome(artefact=result.artefact, summary=result.summary, notes=result.notes)

    async def parse_requirements(self, text: str) -> StageOutcome[RequirementsArtefact]:
        return self._as_outcome(
            await _within((await self._levels.current()).parse_requirements(text))
        )

    async def build_graph(
        self, requirements: list[ParsedRequirement], *, text: str
    ) -> StageOutcome[ArchitectureGraph]:
        return self._as_outcome(
            await _within((await self._levels.current()).build_graph(requirements, text=text))
        )

    async def recommend(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageOutcome[ArchitectureRecommendation]:
        return self._as_outcome(
            await _within((await self._levels.current()).recommend(requirements, graph))
        )

    async def write_uml(self, graph: ArchitectureGraph) -> StageOutcome[UmlArtefact]:
        return self._as_outcome(await _within((await self._levels.current()).write_uml(graph)))

    async def draw_wireframes(
        self,
        graph: ArchitectureGraph,
        *,
        requirement_ids: list[str],
        version: str,
        requirements: list[ParsedRequirement] | None = None,
    ) -> StageOutcome[WireframesArtefact]:
        return self._as_outcome(
            await _within(
                (await self._levels.current()).draw_wireframes(
                    graph,
                    requirement_ids=requirement_ids,
                    version=version,
                    requirements=requirements,
                )
            )
        )

    async def plan_sprint(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageOutcome[SprintPlan]:
        return self._as_outcome(
            await _within((await self._levels.current()).plan_sprint(requirements, graph))
        )

    async def name_project(self, text: str) -> str:
        return await self._c1.name_project(text)


#: Long, because a stage is a model call with a repair loop behind it and the
#: wireframe stage is several. A timeout shorter than the work turns a slow run
#: into a failed one.
STAGE_TIMEOUT_SECONDS = 300.0


class HttpC1:
    """The component, over the wire.

    Every response is validated into the contract type on arrival rather than
    passed along as a dict. The point of generating the schema from these models
    is that a service returning the wrong shape is caught at the boundary it
    crossed, not three stages later when something reads a field that is not
    there.
    """

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        # The remote service holds its own C1_MODEL, and this side has no way to
        # know it without asking. Saying where the answer came from is true;
        # naming a model this process merely configured would not be.
        self.model = f"whatever {self._base_url} is running"
        self._client = client
        self._owned = client is None

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(base_url=self._base_url)
        try:
            response = await client.post(path, json=body, timeout=STAGE_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        finally:
            if self._client is None:
                await client.aclose()

    async def aclose(self) -> None:
        if self._client is not None and self._owned:
            await self._client.aclose()

    async def parse_requirements(self, text: str) -> StageOutcome[RequirementsArtefact]:
        payload = await self._post("/stages/requirements", {"text": text})
        return StageOutcome(
            artefact=RequirementsArtefact.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def build_graph(
        self, requirements: list[ParsedRequirement], *, text: str
    ) -> StageOutcome[ArchitectureGraph]:
        payload = await self._post(
            "/stages/graph",
            {
                "requirements": [r.model_dump(by_alias=True, mode="json") for r in requirements],
                "text": text,
            },
        )
        return StageOutcome(
            artefact=ArchitectureGraph.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def recommend(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageOutcome[ArchitectureRecommendation]:
        payload = await self._post(
            "/stages/recommendation",
            {
                "requirements": [r.model_dump(by_alias=True, mode="json") for r in requirements],
                "graph": graph.model_dump(by_alias=True, mode="json"),
            },
        )
        return StageOutcome(
            artefact=ArchitectureRecommendation.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def write_uml(self, graph: ArchitectureGraph) -> StageOutcome[UmlArtefact]:
        payload = await self._post(
            "/stages/uml", {"graph": graph.model_dump(by_alias=True, mode="json")}
        )
        return StageOutcome(
            artefact=UmlArtefact.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def draw_wireframes(
        self,
        graph: ArchitectureGraph,
        *,
        requirement_ids: list[str],
        version: str,
        requirements: list[ParsedRequirement] | None = None,
    ) -> StageOutcome[WireframesArtefact]:
        payload = await self._post(
            "/stages/wireframes",
            {
                "graph": graph.model_dump(by_alias=True, mode="json"),
                "requirementIds": requirement_ids,
                "version": version,
                "requirements": [
                    one.model_dump(by_alias=True, mode="json") for one in requirements or []
                ],
            },
        )
        return StageOutcome(
            artefact=WireframesArtefact.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def plan_sprint(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageOutcome[SprintPlan]:
        payload = await self._post(
            "/stages/sprint",
            {
                "requirements": [r.model_dump(by_alias=True, mode="json") for r in requirements],
                "graph": graph.model_dump(by_alias=True, mode="json"),
            },
        )
        return StageOutcome(
            artefact=SprintPlan.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def name_project(self, text: str) -> str:
        payload = await self._post("/naming", {"text": text})
        return str(payload["title"])


def make_c1_client(mode: str, *, model: str, base_url: str, thinking: str = "off") -> C1Client:
    """The client the configuration asks for. Over HTTP the service reads its own switch."""
    if mode == "http":
        return HttpC1(base_url)
    return InProcessC1(model, thinking=thinking)
