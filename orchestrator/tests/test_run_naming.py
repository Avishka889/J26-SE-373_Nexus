"""When a run replaces the provisional project name, and when it must not.

No database and no graph. The gate is a predicate, and the failure path is
required never to reach the pool, which is proved here by not giving it one.
"""

import asyncio

import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned import CannedC1
from orchestrator.db import store
from orchestrator.graph import runner as runner_module
from orchestrator.graph.runner import PROVISIONAL_NAME_LIMIT, RunSupervisor, should_title
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db

TRUNCATED = "x" * (PROVISIONAL_NAME_LIMIT + 1)
SHORT = "Build a simple calculator app"


class TestTheGate:
    def test_a_truncated_name_on_the_first_run_is_titled(self) -> None:
        assert should_title(TRUNCATED, 1, []) is True

    def test_a_short_name_is_left_alone(self) -> None:
        """Already a usable name, so a model call would buy nothing."""
        assert should_title(SHORT, 1, []) is False

    def test_a_later_run_never_renames(self) -> None:
        """A name that moves under the reader on every change note is worse than a stale one."""
        assert should_title(TRUNCATED, 2, []) is False
        assert should_title(TRUNCATED, 7, []) is False

    def test_a_name_exactly_at_the_limit_is_left_alone(self) -> None:
        """The client truncates to the limit and appends an ellipsis, so a name
        at exactly the limit was never truncated."""
        assert should_title("x" * PROVISIONAL_NAME_LIMIT, 1, []) is False

    def test_a_short_name_that_is_one_of_the_files_is_titled(self) -> None:
        """The case this feature exists for: a document attached, nothing typed.

        The client falls back to the first filename, so the project is called
        "FOMMP-BRD.pdf". That is short, but nobody chose it and nothing in the
        UI can change it afterwards, so length alone is the wrong question.
        """
        assert should_title("FOMMP-BRD.pdf", 1, ["FOMMP-BRD.pdf"]) is True

    def test_a_short_name_that_is_not_a_filename_is_still_left_alone(self) -> None:
        """Attaching a document does not make a typed name worth replacing."""
        assert should_title(SHORT, 1, ["FOMMP-BRD.pdf"]) is False

    def test_no_files_at_all_is_not_an_error(self) -> None:
        """The column defaults to an empty list, and an older row may have none."""
        assert should_title(SHORT, 1, []) is False
        assert should_title(SHORT, 1, None) is False
        assert should_title(TRUNCATED, 1, None) is True


class TestTheCall:
    async def test_a_naming_failure_is_not_a_run_failure(self) -> None:
        """The provisional name is already on screen and already reasonable.

        `pool=None` on purpose: the failure path is required to return before it
        touches the database, and passing nothing usable proves that rather than
        asserting it.
        """
        component = CannedC1(fails={"naming"})
        runner = RunSupervisor(pool=None, graph=None, c1=component)

        await runner._title_project(
            {"id": "p1", "name": TRUNCATED, "requirement_text": "Build a pharmacy system."},
            {"requirements_version": 1},
        )

        # Returning quietly is only half of it. This also proves the model was
        # actually asked, so the test cannot pass because the gate happened to
        # skip the call for some unrelated reason.
        assert component.calls == ["naming"]

    async def test_a_gated_out_run_never_asks_the_model(self) -> None:
        """Asserted by the component never being asked, not by counting afterwards."""
        component = CannedC1()
        runner = RunSupervisor(pool=None, graph=None, c1=component)

        await runner._title_project(
            {"id": "p1", "name": SHORT, "requirement_text": "Build a calculator."},
            {"requirements_version": 1},
        )

        assert component.calls == []

    async def test_a_project_named_after_its_document_is_sent_to_be_named(self) -> None:
        """Asserted through `_title_project`, because the gate can only widen if
        the runner passes it the row's files. `fails` keeps the pool untouched."""
        component = CannedC1(fails={"naming"})
        runner = RunSupervisor(pool=None, graph=None, c1=component)

        await runner._title_project(
            {
                "id": "p1",
                "name": "FOMMP-BRD.pdf",
                "files": ["FOMMP-BRD.pdf"],
                "requirement_text": "Farmer organisation profiles, business plans and assets.",
            },
            {"requirements_version": 1},
        )

        assert component.calls == ["naming"]

    async def test_empty_requirement_text_is_not_sent_to_be_named(self) -> None:
        component = CannedC1()
        runner = RunSupervisor(pool=None, graph=None, c1=component)

        await runner._title_project(
            {"id": "p1", "name": TRUNCATED, "requirement_text": "   "},
            {"requirements_version": 1},
        )

        assert component.calls == []


class HangingC1:
    model = "hanging (no model)"

    """A component that takes the naming call and never answers it."""

    async def name_project(self, text: str) -> str:
        await asyncio.Event().wait()
        raise AssertionError("the wait above never returns")


class TestTheBound:
    async def test_a_naming_call_that_never_answers_does_not_hold_up_the_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first stage cannot start until this returns, so it has to return.

        Unbounded, this is what a reader sees as every stage reading generating
        and nothing moving, with no stage to blame it on. The bound is shortened
        here so the test is quick: what is asserted is that the wait is bounded
        at all and that hitting the bound is swallowed like any other refusal,
        not the particular number of seconds.
        """
        monkeypatch.setattr(runner_module, "NAMING_TIMEOUT_SECONDS", 0.01)
        runner = RunSupervisor(pool=None, graph=None, c1=HangingC1())

        await asyncio.wait_for(
            runner._title_project(
                {"id": "p1", "name": TRUNCATED, "requirement_text": "Build a pharmacy system."},
                {"requirements_version": 1},
            ),
            # Ten times the bound above: if the runner ever stops applying one,
            # this fails rather than hanging the suite.
            0.1,
        )


class TestTheModelIsOnTheRecord:
    """Which model produced a design, written down when the run starts.

    Nothing recorded it, so a design could not be attributed to the provider
    that made it. Over one working session that cost three separate stretches of
    guessing which of four providers a stored run had come from, and the only way
    to settle it was to ask the person who had run it.

    Read from the client rather than from settings, because the client is built
    once when the process starts. Settings edited afterwards describe a run that
    has not happened yet, and mistaking one for the other is exactly what went
    wrong.
    """

    def test_the_in_process_client_reports_the_model_it_was_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Building the client builds its seven agents, and a provider refuses to
        # construct without a key. Nothing here calls one.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
        from orchestrator.clients.c1 import InProcessC1

        assert InProcessC1("anthropic:claude-haiku-4-5").model == "anthropic:claude-haiku-4-5"

    def test_the_http_client_does_not_invent_a_model_it_cannot_know(self) -> None:
        # The remote service holds its own C1_MODEL. Naming a model this process
        # merely configured would put a false attribution in the audit log.
        from orchestrator.clients.c1 import HttpC1

        model = HttpC1("http://localhost:8001").model
        assert "localhost:8001" in model
        assert "claude" not in model

    def test_a_supervisor_without_a_client_says_so_rather_than_going_quiet(self) -> None:
        # `c1` defaults to None: a supervisor can be built where the graph
        # carries its own client. Skipping the event there would be silent, and
        # silence about which model produced a design is what this event exists
        # to end, so the absence is written down.
        runner = RunSupervisor(pool=None, graph=None)
        recorded = runner._model("c1")
        assert "not recorded" in recorded
        assert recorded.strip() != ""

    def test_a_client_that_names_itself_is_used_verbatim(self) -> None:
        class Fake:
            model = "anthropic:claude-haiku-4-5"

        runner = RunSupervisor(pool=None, graph=None, c1=Fake())
        assert runner._model("c1") == "anthropic:claude-haiku-4-5"


@needs_db
class TestAnOwnersName:
    async def test_a_rename_made_while_the_title_is_asked_for_stands(self, settings) -> None:
        """The title replaces the provisional name and nothing else: a name its
        owner gave it meanwhile was overwritten when the model answered."""
        app = create_app(settings, lifespan_factory=lifespan_for_tests)
        async with app.router.lifespan_context(app):
            async with app.state.pool.connection() as conn:
                project = await store.create_project(
                    conn, name=TRUNCATED, description="", owner_id=DEV_OWNER_ID
                )
            try:
                async with app.state.pool.connection() as conn:
                    await store.patch_project(conn, project["id"], {"name": "Pharmacy"})

                await app.state.supervisor._title_project(
                    {**project, "requirement_text": "Build a pharmacy system.", "files": []},
                    {"requirements_version": 1},
                )

                async with app.state.pool.connection() as conn:
                    kept = await store.project_without_owner_check(conn, project["id"])
                assert kept is not None and kept["name"] == "Pharmacy"
            finally:
                async with app.state.pool.connection() as conn:
                    await store.delete_project(conn, project["id"], owner_id=DEV_OWNER_ID)
