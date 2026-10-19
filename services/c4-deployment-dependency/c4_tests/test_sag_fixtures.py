"""The stub graph C4's impact mapping is developed against, held to C1's and C2's schemas.

The proposal's own plan (Table 11): develop the code-usage and impact package
against a stub Semantic Architecture Graph that conforms to C1's schema, so the
mapping is not blocked on C1's delivery. On this platform C1 is live, so the
stub's job is narrower and still worth doing: a fixture the mapping's tests can
read without a pipeline run, validated by the real models, so a schema change on
either side fails here rather than as a mapping that quietly maps nothing.
"""

import json
from pathlib import Path

import pytest
from sdlc_contracts import ApiContract, ArchitectureGraph, ManifestRow

HERE = Path(__file__).resolve().parent / "fixtures" / "sag"


@pytest.fixture(scope="module")
def graph() -> ArchitectureGraph:
    return ArchitectureGraph.model_validate(json.loads((HERE / "graph.json").read_text()))


@pytest.fixture(scope="module")
def contract() -> ApiContract:
    return ApiContract.model_validate(json.loads((HERE / "contract.json").read_text()))


@pytest.fixture(scope="module")
def manifest() -> list[ManifestRow]:
    return [
        ManifestRow.model_validate(row) for row in json.loads((HERE / "manifest.json").read_text())
    ]


def test_the_graph_is_a_graph_c1_could_have_produced(graph) -> None:
    assert {node.kind for node in graph.nodes} == {"actor", "entity", "service", "constraint"}


def test_every_contract_entity_is_a_graph_entity(graph, contract) -> None:
    """The link the mapping leans on: C2 derives each contract entity from a
    graph entity, by name."""
    entities = {node.label for node in graph.nodes if node.kind == "entity"}
    assert {entity.name for entity in contract.entities} <= entities


def test_every_endpoint_names_its_entity(contract) -> None:
    for endpoint in contract.endpoints:
        schema = endpoint.response or endpoint.request
        assert schema is not None and schema.entity, endpoint.id


def test_the_manifest_names_what_each_file_implements(manifest, contract) -> None:
    endpoints = {endpoint.id for endpoint in contract.endpoints}
    entities = {entity.name for entity in contract.entities}
    named = {item for row in manifest for item in row.implements}
    assert endpoints <= named, "every endpoint is implemented by some file"
    assert entities <= named, "every entity has a model file"
    assert "scr-task-lists" in named, "a screen id the mapping must leave unmapped"
    assert any(not row.implements for row in manifest), "a file that implements nothing"
