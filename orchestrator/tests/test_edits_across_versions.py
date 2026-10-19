# ruff: noqa: F811 - `client` is the rereading fixture, imported to be used by name
"""A person's edit holds in a later version only on the thing it was made to.

Edits are kept beside the artefacts, against an id, and were laid over every
later version by that id alone (review items C1-8, C1-9 and C1-10):

- a requirement keeps its id when a change rewords it, so a correction made to
  the old wording covered the new one, and the change never showed;
- a graph node's id and an assumption's id are their places in a list, so a
  rename or a dismissal landed on whatever stood in that place next time;
- the requirement comparison the healing classifier reads compared the
  artefacts as generated, though the code was built from the corrected ones.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from orchestrator.graph import testing_nodes
from orchestrator.readmodel.assemble import HeldEdits, apply_design_edits, edits_holding
from sdlc_contracts import (
    ArchitectureGraph,
    Assumption,
    GraphNode,
    ParsedRequirement,
    RequirementsArtefact,
)

from .conftest import needs_db
from .test_identity_across_versions import (  # noqa: F401
    ADD,
    CLEAR,
    CLEAR_REWORDED,
    SUBTRACT,
    _advance,
    _note,
    client,
)


def requirement(number: int, text: str) -> ParsedRequirement:
    return ParsedRequirement(
        id=f"R-{number}", text=text, type="functional", priority="must", confidence=70
    )


def assumption(number: int, text: str) -> Assumption:
    return Assumption(id=f"A-{number}", text=text, traces=["R-1"])


def node(node_id: str, kind: str, label: str) -> GraphNode:
    return GraphNode(id=node_id, kind=kind, label=label, position={"x": 0, "y": 0}, traces=["R-1"])


def stored(version: int, artefact: RequirementsArtefact | ArchitectureGraph) -> dict[str, Any]:
    kind = "requirements" if isinstance(artefact, RequirementsArtefact) else "architecture-graph"
    return {"kind": kind, "version": version, "body": artefact.model_dump(by_alias=True)}


def edit(kind: str, target: str, value: Any, *, version: int) -> dict[str, Any]:
    return {
        "kind": kind,
        "target_id": target,
        "value": value,
        "version": version,
        "at": datetime(2026, 10, 11, tzinfo=UTC),
        "by": "you",
    }


def requirements_at(
    version: int, history: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> tuple[list[ParsedRequirement], HeldEdits]:
    held = edits_holding(rows, history, version)
    body = next(
        one["body"]
        for one in history
        if one["kind"] == "requirements" and one["version"] == version
    )
    generated = RequirementsArtefact.model_validate(body).requirements
    _, corrected = apply_design_edits(ArchitectureGraph(), generated, held)
    return corrected, held


def graph_at(
    version: int, history: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> ArchitectureGraph:
    held = edits_holding(rows, history, version)
    body = next(
        one["body"]
        for one in history
        if one["kind"] == "architecture-graph" and one["version"] == version
    )
    graph, _ = apply_design_edits(ArchitectureGraph.model_validate(body), [], held)
    return graph


class TestACorrectedRequirement:
    HISTORY: ClassVar = [
        stored(1, RequirementsArtefact(requirements=[requirement(1, "A shopper pays by card.")])),
        stored(2, RequirementsArtefact(requirements=[requirement(1, "A shopper pays by card.")])),
        stored(
            3,
            RequirementsArtefact(
                requirements=[requirement(1, "A shopper pays by card or by voucher.")]
            ),
        ),
    ]
    CORRECTION = edit("requirement_text", "R-1", "A shopper pays by saved card.", version=1)

    def test_holds_while_the_wording_it_corrected_stands(self) -> None:
        [corrected], held = requirements_at(2, self.HISTORY, [self.CORRECTION])

        assert corrected.text == "A shopper pays by saved card."
        assert corrected.adjusted is True
        assert held.set_aside == {}

    def test_does_not_hide_a_later_change_to_the_requirement(self) -> None:
        [changed], held = requirements_at(3, self.HISTORY, [self.CORRECTION])

        assert changed.text == "A shopper pays by card or by voucher."
        assert changed.adjusted is False
        # Not dropped in silence: the person's words are kept, to be said.
        assert held.set_aside == {"R-1": "A shopper pays by saved card."}

    def test_a_correction_made_to_the_new_wording_holds(self) -> None:
        again = edit("requirement_text", "R-1", "A shopper pays by card or gift card.", version=3)

        [corrected], held = requirements_at(3, self.HISTORY, [self.CORRECTION, again])

        assert corrected.text == "A shopper pays by card or gift card."
        assert held.set_aside == {}

    def test_one_made_after_the_version_asked_for_is_not_read(self) -> None:
        later = edit("requirement_text", "R-1", "A shopper pays by card or gift card.", version=3)

        ranked = edit("requirement_priority", "R-1", "could", version=3)

        [generated], _ = requirements_at(2, self.HISTORY, [later, ranked])

        assert generated.text == "A shopper pays by card."
        assert generated.priority == "must"

    def test_a_priority_follows_the_requirement_whatever_its_wording(self) -> None:
        """A priority is a judgement of the requirement, not of its wording."""
        ranked = edit("requirement_priority", "R-1", "could", version=1)

        [changed], _ = requirements_at(3, self.HISTORY, [ranked])

        assert changed.priority == "could"
        assert changed.priority_corrected is True


class TestARenamedNode:
    HISTORY: ClassVar = [
        stored(
            1,
            ArchitectureGraph(nodes=[node("n1", "entity", "Order"), node("n2", "entity", "Item")]),
        ),
        stored(
            2,
            ArchitectureGraph(
                nodes=[
                    node("n1", "entity", "Customer"),
                    node("n2", "entity", "Order"),
                    node("n3", "service", "Item"),
                ]
            ),
        ),
    ]

    def test_the_rename_follows_the_node_and_not_its_place(self) -> None:
        renamed = edit("node_label", "n1", "Purchase", version=1)

        graph = graph_at(2, self.HISTORY, [renamed])

        assert {one.id: one.label for one in graph.nodes} == {
            "n1": "Customer",
            "n2": "Purchase",
            "n3": "Item",
        }

    def test_a_node_the_new_version_does_not_have_is_not_renamed(self) -> None:
        """Item is a service now: the entity that was renamed is gone."""
        renamed = edit("node_label", "n2", "Line", version=1)

        graph = graph_at(2, self.HISTORY, [renamed])

        assert [one.label for one in graph.nodes] == ["Customer", "Order", "Item"]

    def test_a_rename_at_this_version_goes_by_the_id(self) -> None:
        renamed = edit("node_label", "n1", "Buyer", version=2)

        graph = graph_at(2, self.HISTORY, [renamed])

        assert graph.nodes[0].label == "Buyer"


class TestADecidedAssumption:
    HISTORY: ClassVar = [
        stored(
            1,
            RequirementsArtefact(
                requirements=[requirement(1, "A shopper pays by card.")],
                assumptions=[assumption(1, "Payments are in one currency.")],
            ),
        ),
        stored(
            2,
            RequirementsArtefact(
                requirements=[requirement(1, "A shopper pays by card.")],
                assumptions=[
                    assumption(1, "Refunds go to the card that paid."),
                    assumption(2, "Payments are in one currency."),
                ],
            ),
        ),
    ]

    def test_a_dismissal_follows_the_assumption_and_not_its_place(self) -> None:
        dismissed = edit("assumption_dismissed", "A-1", True, version=1)

        held = edits_holding([dismissed], self.HISTORY, 2)

        assert [(one["kind"], one["target_id"]) for one in held.rows] == [
            ("assumption_dismissed", "A-2")
        ]

    def test_an_edit_to_an_assumption_that_is_gone_is_not_laid_on_another(self) -> None:
        reworded = edit("assumption_text", "A-1", "Payments are in pounds.", version=1)
        history = [
            self.HISTORY[0],
            stored(
                2,
                RequirementsArtefact(
                    requirements=[requirement(1, "A shopper pays by card.")],
                    assumptions=[assumption(1, "Refunds go to the card that paid.")],
                ),
            ),
        ]

        assert edits_holding([reworded], history, 2).rows == []


@needs_db
class TestTheDesignSaysSo:
    async def test_a_change_to_a_corrected_requirement_shows_with_the_correction_beside_it(
        self, client
    ) -> None:
        project_id, run_id = await _calculator(client)
        first = (await client.get(f"/projects/{project_id}/design")).json()["requirements"]
        clear = next(one["id"] for one in first if one["text"] == CLEAR)
        correction = "The calculator clears the entry when C is pressed."
        await client.patch(
            f"/projects/{project_id}/design/requirements/{clear}", json={"text": correction}
        )

        await _note(client, project_id, run_id, "Add a history screen")

        second = (await client.get(f"/projects/{project_id}/design")).json()["requirements"]
        changed = next(one for one in second if one["id"] == clear)
        assert changed["text"] == CLEAR_REWORDED
        assert changed["adjusted"] is False
        assert changed["setAsideCorrection"] == correction
        others = [one for one in second if one["id"] != clear]
        assert all(one["setAsideCorrection"] is None for one in others)

    async def test_a_rename_is_on_the_node_it_was_made_to_after_the_graph_is_redrawn(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id, run_id = await _calculator(client)
        renamed = await client.patch(
            f"/projects/{project_id}/design/graph/nodes/e1", json={"label": "Ledger Entry"}
        )
        assert renamed.status_code == 200, renamed.text
        c1 = client.app.state.c1
        drawn = c1.build_graph

        async def redrawn(requirements, *, text):  # type: ignore[no-untyped-def]
            """The same graph with a new entity ahead of the one that was renamed."""
            outcome = await drawn(requirements, text=text)
            graph = outcome.artefact
            record = next(one for one in graph.nodes if one.id == "e1")
            nodes = [
                record.model_copy(update={"label": "Customer"}),
                record.model_copy(update={"id": "e2"}),
                *[one for one in graph.nodes if one.id != "e1"],
            ]
            return type(outcome)(
                artefact=graph.model_copy(update={"nodes": nodes}),
                summary=outcome.summary,
                notes=outcome.notes,
            )

        monkeypatch.setattr(c1, "build_graph", redrawn)
        await _note(client, project_id, run_id, "Add a history screen")

        design = (await client.get(f"/projects/{project_id}/design")).json()
        assert design["requirementsVersion"] == 2
        labels = {one["id"]: one["label"] for one in design["graph"]["nodes"]}
        assert labels["e1"] == "Customer"
        assert labels["e2"] == "Ledger Entry"


@needs_db
class TestTheHealingComparisonReadsWhatWasBuilt:
    async def test_a_correction_made_between_two_builds_is_a_change(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The code is built from the corrected requirement, so a test that
        fails after the correction traces to something that changed."""
        project_id, run_id = await _calculator(client)
        await _note(client, project_id, run_id, "Add a history screen")
        second = (await client.get(f"/projects/{project_id}/design")).json()["requirements"]
        add = next(one["id"] for one in second if one["text"] == ADD)
        correction = "The calculator adds two numbers and rounds to two places."
        await client.patch(
            f"/projects/{project_id}/design/requirements/{add}", json={"text": correction}
        )

        diff = await _diff_between_builds(client, project_id, monkeypatch)

        assert diff is not None
        [change] = [one for one in diff.changed if one.requirement_id == add]
        assert (change.field, change.before, change.after) == ("text", ADD, correction)

    async def test_a_correction_both_builds_read_is_not(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id, run_id = await _calculator(client)
        first = (await client.get(f"/projects/{project_id}/design")).json()["requirements"]
        subtract = next(one["id"] for one in first if one["text"] == SUBTRACT)
        await client.patch(
            f"/projects/{project_id}/design/requirements/{subtract}",
            json={"text": "The calculator subtracts two numbers and may go negative."},
        )
        await _note(client, project_id, run_id, "Add a history screen")

        diff = await _diff_between_builds(client, project_id, monkeypatch)

        assert diff is not None
        assert subtract not in {one.requirement_id for one in diff.changed}


async def _calculator(client) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    from .test_identity_across_versions import READINGS

    created = await client.post("/projects", json={"name": "Calculator", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)
    await client.patch(f"/projects/{project_id}", json={"requirementText": "\n".join(READINGS[0])})
    run_id = (await client.get("/runs", params={"project": project_id})).json()[0]["id"]
    await _advance(client, run_id)
    return project_id, run_id


async def _diff_between_builds(client, project_id: str, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """The comparison healing is handed for code version 2 against 1, each built
    from the design version of the same number."""

    async def design_version(pool: Any, project: str, code_version: int) -> int:
        return code_version

    monkeypatch.setattr(testing_nodes, "_design_version_for", design_version)
    return await testing_nodes._requirement_diff(
        client.app.state.pool, {"project_id": project_id, "code_version": 2}, 1
    )
