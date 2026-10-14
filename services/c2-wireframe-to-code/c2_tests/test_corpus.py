"""The corpus parses, whole: a design that stops parsing is a schema break.

extra="forbid" means these files fail loudly the moment a contract field is
renamed rather than added, which is the point: the corpus is stored data, and
only additive changes are safe once data is stored.
"""

import pytest
from c2.rules.scope import derive_scope

from .corpus_io import design_files, load_design, load_truth


@pytest.mark.parametrize("path", design_files(), ids=lambda p: p.stem)
def test_every_design_parses_into_the_contracts(path) -> None:
    design = load_design(path)
    assert design.graph.nodes and design.graph.edges
    assert design.wireframes.flows
    assert design.sprint.proposed


@pytest.mark.parametrize("path", design_files(), ids=lambda p: p.stem)
def test_every_design_yields_a_scope_with_screens(path) -> None:
    """Scope derivation is the first C2 stage; a corpus item it cannot ground
    would silently test nothing downstream."""
    design = load_design(path)
    scope = derive_scope(design.sprint, design.wireframes)
    assert scope.in_scope_ids, f"{design.name} proposes no stories"
    screens = {
        screen for story in scope.stories if story.in_scope for screen in story.traces.screen_ids
    }
    assert screens, f"{design.name} grounds no story in any screen"


def test_the_calculator_truth_parses() -> None:
    truth = load_truth("calculator")
    assert {e.method for e in truth.endpoints} == {"GET", "POST"}
