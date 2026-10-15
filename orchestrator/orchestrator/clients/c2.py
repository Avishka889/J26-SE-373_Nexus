"""How the orchestrator reaches Component 2.

The same seam C1 has, for the same reasons: one protocol, two implementations,
chosen by configuration, with the generated contract types crossing the
boundary either way. Nothing in the orchestrator knows how a contract is
inferred from a screen or how a route file is written.

Two shapes here are not C1's, because C2 produces two things a design stage
does not. The code stages produce files, so they answer with bodies to store
plus manifest rows to show rather than with one artefact; and the push answers
with an outcome, because "no connection, so nothing was pushed" is a result to
record and not an error to raise.

`StageOutcome` is imported from the C1 client rather than copied: it is one
shape (artefact, summary, notes) and it happened to be written there first.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from sdlc_contracts import (
    ApiContract,
    ApiContractArtefact,
    ArchitectureGraph,
    ArchitectureRecommendation,
    BuildReport,
    ContractAgreement,
    EarlierPage,
    ManifestRow,
    ParsedRequirement,
    RepositoryPointer,
    SprintPlan,
    SprintScope,
    TechStackArtefact,
    WireframesArtefact,
)

from .c1 import StageOutcome
from .thinking import Levelled, thinking_sent

Arm = Literal["rule", "llm", "merged"]


@dataclass(frozen=True)
class FilesOutcome:
    """What a code generating stage produced.

    The bodies are stored and served from their own route; the manifest is what
    the snapshot carries, because the client polls it every 1.2 seconds and a
    generated monorepo is tens of files.
    """

    files: dict[str, str]
    manifest: list[ManifestRow]
    summary: str
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PushOutcome:
    """Exactly one side is set: where the code went, or why it did not go."""

    pointer: RepositoryPointer | None = None
    reason: str | None = None


@dataclass(frozen=True)
class LandOutcome:
    """Where the default branch went for an approved version, or why it did not."""

    commit_sha: str | None = None
    #: "fast-forward", "landing commit", or "already there".
    how: str = ""
    reason: str | None = None


class C2Client(Protocol):
    """The seven stage calls Component 2 answers, plus the push.

    Per stage for C1's reason: each is a stage the reader watches move, and a
    crash should cost the stage that was running. The push is not a stage of
    its own; it is the tail of the build stage, separated because it needs the
    owner's decrypted token and the build does not.
    """

    #: What produced the artefacts, for the record on a run.
    model: str

    async def derive_scope(
        self, sprint: SprintPlan, wireframes: WireframesArtefact
    ) -> StageOutcome[SprintScope]: ...

    async def propose_stack(
        self, graph: ArchitectureGraph, recommendation: ArchitectureRecommendation | None = None
    ) -> StageOutcome[TechStackArtefact]: ...

    async def infer_contract(
        self,
        version: int,
        graph: ArchitectureGraph,
        wireframes: WireframesArtefact,
        scope: SprintScope,
        *,
        arm: Arm = "rule",
        criteria: Sequence[str] = (),
    ) -> StageOutcome[ApiContractArtefact]: ...

    async def generate_frontend(
        self,
        project_name: str,
        contract: ApiContract,
        wireframes: WireframesArtefact,
        scope: SprintScope,
        *,
        design_version: int,
        arm: str,
        fill: bool = False,
        requirements: list[ParsedRequirement] | None = None,
        earlier: list[EarlierPage] | None = None,
    ) -> FilesOutcome: ...

    async def generate_backend(
        self, contract: ApiContract, *, arm: str = "rule", fill: bool = False
    ) -> FilesOutcome: ...

    async def check_agreement(
        self, contract: ApiContract, sources: dict[str, str]
    ) -> StageOutcome[ContractAgreement]: ...

    async def build(
        self, sources: dict[str, str], *, on_step: Callable[[str], None] | None = None
    ) -> StageOutcome[BuildReport]: ...

    async def push(
        self,
        files: dict[str, str],
        *,
        name: str,
        token: str | None,
        message: str,
        branch: str | None = None,
    ) -> PushOutcome: ...

    async def land(
        self, pointer: RepositoryPointer, *, token: str | None, message: str
    ) -> LandOutcome: ...


class InProcessC2:
    """The component, imported and called directly.

    The import is deferred to construction, so an orchestrator deployed to talk
    to C2 over HTTP does not need the component's dependencies installed.
    """

    def __init__(self, model: Any, *, thinking: str = "off") -> None:
        try:
            from c2.agents import settings_for
            from c2.service import C2
        except ModuleNotFoundError as exc:  # pragma: no cover - deployment shape
            raise RuntimeError(
                "C2_MODE is 'inprocess' but the component is not installed. "
                "Install the sdlc-c2 package, or set C2_MODE=http and C2_BASE_URL."
            ) from exc
        # One component per thinking level, as C1's client keeps them (3B).
        self._levels = Levelled(lambda level: C2(model, thinking=level), thinking, opens=True)
        self._model = model
        self._settings_for = settings_for
        self.model = str(model)
        #: The configured level, which a run uses where its account chose none.
        self.level = thinking
        # What every agent's request says about thinking, as C1's client reads it.
        self.thinking = self.thinking_for(thinking)

    @property
    def _c2(self) -> Any:
        """The component at the configured level."""
        return self._levels.configured

    def thinking_for(self, level: str) -> str:
        """What this component's requests say about thinking at a level, as a run records it."""
        return thinking_sent(self._settings_for(self._model, thinking=level))

    async def __aenter__(self) -> "InProcessC2":
        await self._levels.open()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._levels.close(*args)

    @staticmethod
    def _as_outcome(result: Any) -> StageOutcome[Any]:
        return StageOutcome(artefact=result.artefact, summary=result.summary, notes=result.notes)

    @staticmethod
    def _as_files(result: Any, arm: str) -> FilesOutcome:
        return FilesOutcome(
            files={generated.path: generated.content for generated in result.artefact.files},
            manifest=result.artefact.manifest(arm),
            summary=result.summary,
            notes=result.notes,
        )

    async def derive_scope(
        self, sprint: SprintPlan, wireframes: WireframesArtefact
    ) -> StageOutcome[SprintScope]:
        return self._as_outcome(
            await (await self._levels.current()).derive_scope(sprint, wireframes)
        )

    async def propose_stack(
        self, graph: ArchitectureGraph, recommendation: ArchitectureRecommendation | None = None
    ) -> StageOutcome[TechStackArtefact]:
        return self._as_outcome(
            await (await self._levels.current()).propose_stack(graph, recommendation)
        )

    async def infer_contract(
        self,
        version: int,
        graph: ArchitectureGraph,
        wireframes: WireframesArtefact,
        scope: SprintScope,
        *,
        arm: Arm = "rule",
        criteria: Sequence[str] = (),
    ) -> StageOutcome[ApiContractArtefact]:
        return self._as_outcome(
            await (await self._levels.current()).infer_contract(
                version, graph, wireframes, scope, arm=arm, criteria=criteria
            )
        )

    async def generate_frontend(
        self,
        project_name: str,
        contract: ApiContract,
        wireframes: WireframesArtefact,
        scope: SprintScope,
        *,
        design_version: int,
        arm: str,
        fill: bool = False,
        requirements: list[ParsedRequirement] | None = None,
        earlier: list[EarlierPage] | None = None,
    ) -> FilesOutcome:
        return self._as_files(
            await (await self._levels.current()).generate_frontend(
                project_name,
                contract,
                wireframes,
                scope,
                design_version=design_version,
                arm=arm,
                fill=fill,
                requirements=requirements,
                earlier=earlier or [],
            ),
            arm,
        )

    async def generate_backend(
        self, contract: ApiContract, *, arm: str = "rule", fill: bool = False
    ) -> FilesOutcome:
        return self._as_files(
            await (await self._levels.current()).generate_backend(contract, fill=fill), arm
        )

    async def check_agreement(
        self, contract: ApiContract, sources: dict[str, str]
    ) -> StageOutcome[ContractAgreement]:
        return self._as_outcome(
            await (await self._levels.current()).check_agreement(contract, sources)
        )

    async def build(
        self, sources: dict[str, str], *, on_step: Callable[[str], None] | None = None
    ) -> StageOutcome[BuildReport]:
        return self._as_outcome(
            await (await self._levels.current()).build(sources, on_step=on_step)
        )

    async def push(
        self,
        files: dict[str, str],
        *,
        name: str,
        token: str | None,
        message: str,
        branch: str | None = None,
    ) -> PushOutcome:
        result = await (await self._levels.current()).push(
            files, name=name, token=token, message=message, branch=branch
        )
        return PushOutcome(pointer=result.pointer, reason=result.reason)

    async def land(
        self, pointer: RepositoryPointer, *, token: str | None, message: str
    ) -> LandOutcome:
        result = await (await self._levels.current()).land(pointer, token=token, message=message)
        return LandOutcome(commit_sha=result.commit_sha, how=result.how, reason=result.reason)


#: Long for C1's reason: a stage is model calls with a repair loop behind them.
STAGE_TIMEOUT_SECONDS = 300.0

#: Longer still, because the build stage is a real npm install, typecheck and
#: test run. The sandbox caps each step at seven minutes, so a timeout under
#: the sum of those would turn a slow build into a failed run.
BUILD_TIMEOUT_SECONDS = 1500.0


class HttpC2:
    """The component, over the wire.

    Every response is validated into the contract type on arrival, so a service
    answering the wrong shape is caught at the boundary it crossed.
    """

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = f"whatever {self._base_url} is running"
        self._client = client
        self._owned = client is None

    async def _post(
        self, path: str, body: dict[str, Any], *, timeout: float = STAGE_TIMEOUT_SECONDS
    ) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(base_url=self._base_url)
        try:
            response = await client.post(path, json=body, timeout=timeout)
            response.raise_for_status()
            return response.json()
        finally:
            if self._client is None:
                await client.aclose()

    async def aclose(self) -> None:
        if self._client is not None and self._owned:
            await self._client.aclose()

    @staticmethod
    def _wire(model: Any) -> dict[str, Any]:
        return model.model_dump(by_alias=True, mode="json")

    @staticmethod
    def _files_outcome(payload: dict[str, Any]) -> FilesOutcome:
        return FilesOutcome(
            files=payload["files"],
            manifest=[ManifestRow.model_validate(row) for row in payload["manifest"]],
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def derive_scope(
        self, sprint: SprintPlan, wireframes: WireframesArtefact
    ) -> StageOutcome[SprintScope]:
        payload = await self._post(
            "/stages/sprint-scope",
            {"sprint": self._wire(sprint), "wireframes": self._wire(wireframes)},
        )
        return StageOutcome(
            artefact=SprintScope.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def propose_stack(
        self, graph: ArchitectureGraph, recommendation: ArchitectureRecommendation | None = None
    ) -> StageOutcome[TechStackArtefact]:
        payload = await self._post(
            "/stages/tech-stack",
            {
                "graph": self._wire(graph),
                "recommendation": self._wire(recommendation) if recommendation else None,
            },
        )
        return StageOutcome(
            artefact=TechStackArtefact.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def infer_contract(
        self,
        version: int,
        graph: ArchitectureGraph,
        wireframes: WireframesArtefact,
        scope: SprintScope,
        *,
        arm: Arm = "rule",
        criteria: Sequence[str] = (),
    ) -> StageOutcome[ApiContractArtefact]:
        payload = await self._post(
            "/stages/api-contract",
            {
                "version": version,
                "graph": self._wire(graph),
                "wireframes": self._wire(wireframes),
                "scope": self._wire(scope),
                "arm": arm,
                "criteria": list(criteria),
            },
        )
        return StageOutcome(
            artefact=ApiContractArtefact.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def generate_frontend(
        self,
        project_name: str,
        contract: ApiContract,
        wireframes: WireframesArtefact,
        scope: SprintScope,
        *,
        design_version: int,
        arm: str,
        fill: bool = False,
        requirements: list[ParsedRequirement] | None = None,
        earlier: list[EarlierPage] | None = None,
    ) -> FilesOutcome:
        return self._files_outcome(
            await self._post(
                "/stages/frontend-code",
                {
                    "projectName": project_name,
                    "contract": self._wire(contract),
                    "wireframes": self._wire(wireframes),
                    "scope": self._wire(scope),
                    "designVersion": design_version,
                    "arm": arm,
                    "fill": fill,
                    "requirements": [self._wire(one) for one in requirements or []],
                    "earlier": [self._wire(one) for one in earlier or []],
                },
            )
        )

    async def generate_backend(
        self, contract: ApiContract, *, arm: str = "rule", fill: bool = False
    ) -> FilesOutcome:
        return self._files_outcome(
            await self._post(
                "/stages/backend-code",
                {"contract": self._wire(contract), "arm": arm, "fill": fill},
            )
        )

    async def check_agreement(
        self, contract: ApiContract, sources: dict[str, str]
    ) -> StageOutcome[ContractAgreement]:
        payload = await self._post(
            "/stages/contract-agreement",
            {"contract": self._wire(contract), "sources": sources},
        )
        return StageOutcome(
            artefact=ContractAgreement.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def build(
        self, sources: dict[str, str], *, on_step: Callable[[str], None] | None = None
    ) -> StageOutcome[BuildReport]:
        """`on_step` is the in process heartbeat hook and has no wire form.

        Over HTTP the run leans on the component's longer stale window instead,
        which is what `stale_after_seconds` on the registry entry is for.
        """
        payload = await self._post(
            "/stages/build", {"sources": sources}, timeout=BUILD_TIMEOUT_SECONDS
        )
        return StageOutcome(
            artefact=BuildReport.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes", {}),
        )

    async def push(
        self,
        files: dict[str, str],
        *,
        name: str,
        token: str | None,
        message: str,
        branch: str | None = None,
    ) -> PushOutcome:
        payload = await self._post(
            "/push",
            {"files": files, "name": name, "token": token, "message": message, "branch": branch},
        )
        pointer = payload.get("pointer")
        return PushOutcome(
            pointer=RepositoryPointer.model_validate(pointer) if pointer else None,
            reason=payload.get("reason"),
        )

    async def land(
        self, pointer: RepositoryPointer, *, token: str | None, message: str
    ) -> LandOutcome:
        payload = await self._post(
            "/land",
            {
                "pointer": pointer.model_dump(by_alias=True, mode="json"),
                "token": token,
                "message": message,
            },
        )
        return LandOutcome(
            commit_sha=payload.get("commitSha"),
            how=payload.get("how") or "",
            reason=payload.get("reason"),
        )


def make_c2_client(mode: str, *, model: str, base_url: str, thinking: str = "off") -> C2Client:
    """The client the configuration asks for. Over HTTP the service reads its own switch."""
    if mode == "http":
        return HttpC2(base_url)
    return InProcessC2(model, thinking=thinking)
