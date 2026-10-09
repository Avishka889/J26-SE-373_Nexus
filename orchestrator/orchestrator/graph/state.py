"""The run state LangGraph checkpoints.

Ids, versions and counters only. Artefact bodies go to Postgres, because a
checkpoint is opaque msgpack that nothing can query, and because the artefacts
are the thing the evaluation reads.
"""

import operator
from typing import Annotated, TypedDict


class C1RunState(TypedDict, total=False):
    project_id: str
    run_id: str
    requirements_version: int
    input_text: str
    #: Accumulated across revisions, so the parse node sees every note in order
    #: rather than only the latest one.
    revision_notes: Annotated[list[str], operator.add]
    #: Bounds the repair and revision loops.
    attempt: int
    #: How many questions the latest Requirements Analysis asked, which is what
    #: decides whether the run pauses for them before building the rest.
    asked: int
    #: How many times this generation has paused for questions. Back to zero when
    #: the review requests changes, since a new generation may ask again.
    paused: int


class C2RunState(TypedDict, total=False):
    """The code run's state: two version axes and nothing else.

    No arm, no stack, no scope. Those are the human's decisions and they live
    as overlays, read by the node that needs them: a choice copied into
    checkpointed state would be the version of it that was true when the run
    started, and a run that pauses at the gate for a day would resume with a
    stale one.
    """

    project_id: str
    run_id: str
    #: This phase's own counter, allocated by the store.
    code_version: int
    #: The upstream version this run reads design artefacts at, pinned when
    #: the run is created so the design moving on cannot change it mid run.
    design_version: int
    attempt: int


class C3RunState(TypedDict, total=False):
    """The testing run's state: two version axes, as C2 has.

    No target, no findings, no failures. The target is the human's choice and
    lives as an overlay; the reports live as artefacts. Checkpointed state
    carries only what the graph needs to find them again, because a run that
    pauses at its gate for a day should resume against what is true then
    rather than against a copy of what was true when it started.
    """

    project_id: str
    run_id: str
    #: This phase's own counter, allocated by the store.
    test_version: int
    #: The code version this run tests, pinned when the run is created so a
    #: regeneration mid run cannot change what the tests were run against.
    code_version: int
    attempt: int


class C4RunState(TypedDict, total=False):
    """The deployment run's state: its own axis and the two it reads.

    Ids and versions only, as the other phases keep. The code version is not
    known when the run is created, because a run pins a test version and the
    code version is whatever that test version tested; the first stage looks it
    up once and every later stage reads the same one, so code regenerated while
    a deployment run is in flight cannot change what it analyses.
    """

    project_id: str
    run_id: str
    #: This phase's own counter, allocated by the store.
    deploy_version: int
    #: The test version whose approval this run starts from.
    test_version: int
    #: The code version that test version tested, pinned by the first stage.
    code_version: int
    attempt: int
    #: Who approved the release at the gate, which gate, and whether the
    #: decision carried the go ahead a cloud release needs.
    release_authorisation: dict
