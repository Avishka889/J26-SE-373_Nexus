"""The one hand written identifier list the frontend still keeps.

The display contract itself no longer needs a drift test: since 2026-08-19
`features/requirements/api/types.ts` re-exports the generated
`packages/contracts-ts` types, so the interfaces the browser compiles against
are derived from the Pydantic models by construction. The twenty pair field
comparison this file used to run died with the hand written copy it policed.

What cannot be generated is the stage id tuples in `src/types/project.ts`: the
frontend's shared and entity layers read them directly, and each is the canonical
vocabulary shared by the contract schema names, the endpoint paths and the run
event stage keys. One hand written list per phase, one equality check each.
"""

import re
from pathlib import Path

from sdlc_contracts import CODE_STAGE_IDS, DEPLOY_STAGE_IDS, DESIGN_STAGE_IDS, TEST_STAGE_IDS

FRONTEND_SRC = Path(__file__).resolve().parents[3] / "ai-sdlc-platform-frontend" / "src"


def _frontend_ids(name: str) -> tuple[str, ...]:
    project_ts = FRONTEND_SRC / "types" / "project.ts"
    assert project_ts.exists(), f"expected the stage id tuples at {project_ts}"
    source = project_ts.read_text(encoding="utf-8")
    block = re.search(rf"{name} = \[(.*?)\] as const", source, re.DOTALL)
    assert block, f"{name} is no longer declared where it was"
    return tuple(re.findall(r'"([a-z-]+)"', block.group(1)))


def test_design_stage_ids_match() -> None:
    assert _frontend_ids("DESIGN_STAGE_IDS") == DESIGN_STAGE_IDS


def test_code_stage_ids_match() -> None:
    """The same check for the code phase. Two hand written lists now, because
    the browser's shared and entity layers read both and neither may import a
    feature; two equality checks keep both honest."""
    assert _frontend_ids("CODE_STAGE_IDS") == CODE_STAGE_IDS


def test_test_stage_ids_match() -> None:
    assert _frontend_ids("TEST_STAGE_IDS") == TEST_STAGE_IDS


def test_deploy_stage_ids_match() -> None:
    """Ten stages, the last two carried out by the orchestrator after the gate:
    the order is the stepper's, so a swapped pair would show a release before
    the review that authorises it."""
    assert _frontend_ids("DEPLOY_STAGE_IDS") == DEPLOY_STAGE_IDS


def test_the_display_contract_is_a_re_export() -> None:
    """The guarantee the twenty pair comparison was replaced by.

    If somebody starts hand writing interfaces in types.ts again, the by
    construction argument is gone and the field comparison this file used to
    run would need to come back. Catch the regression at its root instead:
    the file must keep importing the generated package.
    """
    types_ts = FRONTEND_SRC / "features" / "requirements" / "api" / "types.ts"
    source = types_ts.read_text(encoding="utf-8")
    assert '"@sdlc/contracts-ts"' in source, (
        "types.ts no longer re-exports the generated contract types; either "
        "restore the re-export or bring back the field for field drift test"
    )
