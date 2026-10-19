"""The changelog signal on scripted answers: every claim checked, the level the rule's.

A model is replaced by a function that answers as a real one could, including
wrongly: a sentence it made up, a sentence from the wrong release, a symbol its
own sentence does not name, and a level of its own that disagrees with the
notes. What is checked is that each of those is refused for its own reason and
counted, that nothing refused moves the level, that the level is the rule's and
never the model's, and that a model which did not answer leaves the signal
abstaining rather than reporting a quiet release.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx
from c4.app import create_app
from c4.risk.changelog import analyse
from c4.service import C4
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage
from sdlc_contracts import (
    ChangelogReport,
    DependencyUpdate,
    DependencyUpdates,
    ReleaseNoteRef,
    update_id_for,
    update_key,
)

MODEL = "deepseek:deepseek-flash"

NOTES = """## 5.1.0
- Added support for `res.links()` with several `rel` values.

## 5.0.0
- Removed `app.del()`; use `app.delete()` instead.
- `req.query` is now a getter and no longer writable.

### 4.21.2
- Removed the `debug` export."""

REMOVAL = {
    "kind": "removal",
    "symbols": ["app.del"],
    "quote": "Removed `app.del()`; use `app.delete()` instead.",
    "version": "5.0.0",
}
BEHAVIOUR = {
    "kind": "behavioural",
    "symbols": ["req.query"],
    "quote": "`req.query` is now a getter and no longer writable.",
    "version": "5.0.0",
}
FEATURE = {
    "kind": "feature",
    "symbols": ["res.links"],
    "quote": "Added support for `res.links()` with several `rel` values.",
    "version": "5.1.0",
}
INVENTED = {
    "kind": "removal",
    "symbols": ["app.param"],
    "quote": "Removed `app.param()`.",
    "version": "5.0.0",
}
#: Real, but under a heading nested in the 5.0.0 body that names the installed version.
OUTSIDE = {
    "kind": "removal",
    "symbols": [],
    "quote": "Removed the `debug` export.",
    "version": "4.21.2",
}
#: The removal sentence, naming a symbol the sentence does not contain.
MISNAMED = {**REMOVAL, "symbols": ["app.delete", "router.del"]}
#: A sentence from the request's own framing, which describes no release.
FRAMING = {
    "kind": "other",
    "symbols": [],
    "quote": "Installed version: 4.21.2.",
    "version": "5.1.0",
}
EMPTY = {"kind": "other", "symbols": [], "quote": "   ", "version": "5.0.0"}


def _update(package: str = "express", *, notes: str | None = NOTES) -> DependencyUpdate:
    key = update_key("npm", package, "4.21.2", "5.1.0")
    path = f"notes/{package}/github-release-5.1.0.md"
    refs = (
        [
            ReleaseNoteRef(
                source="github-release",
                url=f"https://github.com/example/{package}/releases",
                version="5.1.0",
                path=path,
                sha256=hashlib.sha256(notes.encode()).hexdigest(),
                chars=len(notes),
            )
        ]
        if notes is not None
        else []
    )
    return DependencyUpdate(
        id=update_id_for(key),
        key=key,
        ecosystem="npm",
        package=package,
        manifest_path="apps/api/package.json",
        scope="prod",
        declared="^4.21.2",
        from_version="4.21.2",
        to_version="5.1.0",
        candidate="latest",
        change="major",
        notes=refs,
    )


def _updates(*updates: DependencyUpdate) -> DependencyUpdates:
    return DependencyUpdates(
        version=1,
        generated_at=datetime(2026, 9, 27, tzinfo=UTC),
        code_version=1,
        test_version=1,
        target="generated",
        updates=list(updates),
    )


def _texts(*updates: DependencyUpdate, text: str = NOTES) -> dict[str, str]:
    return {ref.path: text for update in updates for ref in update.notes}


def _answering(
    claims: list[dict[str, Any]], *, stated: str = "high", calls: list[int] | None = None
) -> FunctionModel:
    def respond(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if calls is not None:
            calls.append(1)
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name, {"claims": claims, "stated_level": stated})
            ]
        )

    return FunctionModel(respond)


async def _one(claims: list[dict[str, Any]], **kwargs) -> ChangelogReport:
    update = _update()
    return await analyse(
        _updates(update),
        _texts(update),
        model=MODEL,
        version=1,
        agent_model=_answering(claims, **kwargs),
    )


class TestTheLevelIsTheRules:
    async def test_a_verified_removal_is_high_whatever_the_model_says(self) -> None:
        report = await _one([REMOVAL], stated="low")
        analysis = report.per_update[0]
        assert analysis.vote.level == "high"
        assert analysis.model is not None and analysis.model.stated_level == "low"
        assert "removal of app.del in 5.0.0" in analysis.vote.rationale
        assert analysis.vote.evidence_ids == [analysis.claims[0].id]

    async def test_a_fabricated_claim_neither_raises_nor_lowers_the_level(self) -> None:
        """An invented removal beside a real feature leaves the feature's Low."""
        report = await _one([FEATURE, INVENTED])
        analysis = report.per_update[0]
        assert analysis.vote.level == "low"
        assert [refused.reason for refused in analysis.refused] == ["quote-not-found"]
        assert report.claims_verified == 1 and report.claims_refused == 1

    async def test_every_claim_refused_is_an_abstention_not_a_quiet_release(self) -> None:
        analysis = (await _one([INVENTED])).per_update[0]
        assert analysis.vote.level is None
        assert "every claim the model made was refused" in analysis.vote.abstained_reason

    async def test_notes_that_state_nothing_rated_are_a_quiet_release(self) -> None:
        assert (await _one([])).per_update[0].vote.level == "low"

    async def test_a_behaviour_change_without_a_removal_is_medium(self) -> None:
        assert (await _one([FEATURE, BEHAVIOUR])).per_update[0].vote.level == "medium"


class TestTheCheck:
    async def test_each_kind_of_bad_claim_is_refused_for_its_own_reason(self) -> None:
        analysis = (await _one([INVENTED, OUTSIDE, MISNAMED, FRAMING, EMPTY, FEATURE])).per_update[
            0
        ]
        assert [refused.reason for refused in analysis.refused] == [
            "quote-not-found",
            "outside-version-window",
            "symbol-not-in-quote",
            "no-such-source",
            "empty-quote",
        ]
        assert [claim.kind for claim in analysis.claims] == ["feature"]

    async def test_the_release_recorded_is_where_the_sentence_is_not_where_the_model_said(
        self,
    ) -> None:
        mislabelled = {**REMOVAL, "version": "5.1.0"}
        claim = (await _one([mislabelled])).per_update[0].claims[0]
        assert claim.version == "5.0.0"
        assert claim.source_url == "https://github.com/example/express/releases"

    async def test_a_rewrapped_sentence_is_the_same_sentence(self) -> None:
        rewrapped = {**REMOVAL, "quote": "Removed `app.del()`;\n  use `app.delete()` instead."}
        assert (await _one([rewrapped])).per_update[0].vote.level == "high"


class TestWhatIsShown:
    async def test_no_notes_abstains_and_asks_no_one(self) -> None:
        calls: list[int] = []
        update = _update(notes=None)
        report = await analyse(
            _updates(update), {}, model=MODEL, version=1, agent_model=_answering([], calls=calls)
        )
        analysis = report.per_update[0]
        assert calls == []
        assert analysis.model is None and not analysis.notes_found
        assert "no release notes were found" in analysis.vote.abstained_reason

    async def test_notes_a_rate_limit_kept_out_abstain_saying_so(self) -> None:
        calls: list[int] = []
        update = _update(notes=None).model_copy(
            update={"notes_unavailable": "GitHub answered with its rate limit"}
        )
        report = await analyse(
            _updates(update), {}, model=MODEL, version=1, agent_model=_answering([], calls=calls)
        )
        assert calls == []
        assert report.per_update[0].vote.abstained_reason == "GitHub answered with its rate limit"

    async def test_notes_that_changed_since_they_were_read_are_not_shown(self) -> None:
        calls: list[int] = []
        update = _update()
        report = await analyse(
            _updates(update),
            _texts(update, text=NOTES + "\n- Removed everything."),
            model=MODEL,
            version=1,
            agent_model=_answering([REMOVAL], calls=calls),
        )
        assert calls == []
        assert "not the text that was fetched" in report.per_update[0].vote.abstained_reason

    async def test_the_windows_read_are_oldest_first_by_the_ecosystems_order(self) -> None:
        analysis = (await _one([FEATURE])).per_update[0]
        assert analysis.windows == ["4.21.2", "5.0.0", "5.1.0"]


def _failing(status: int, on_call: int, calls: list[int]) -> FunctionModel:
    def respond(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        if len(calls) == on_call:
            raise ModelHTTPError(status_code=status, model_name="scripted", body={"error": "no"})
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name, {"claims": [REMOVAL], "stated_level": "high"}
                )
            ]
        )

    return FunctionModel(respond)


class TestAModelThatDidNotAnswer:
    async def test_a_rate_limit_stops_the_stage_and_nothing_after_it_is_asked(self) -> None:
        calls: list[int] = []
        first, second, third = _update("alpha"), _update("beta"), _update("gamma")
        report = await analyse(
            _updates(first, second, third),
            _texts(first, second, third),
            model=MODEL,
            version=1,
            agent_model=_failing(429, 2, calls),
        )
        assert len(calls) == 2
        answered, limited, skipped = report.per_update
        assert answered.vote.level == "high"
        assert limited.model is not None and limited.model.outcome == "rate-limited"
        assert limited.vote.level is None and limited.vote.abstained_reason.startswith(
            "rate-limited"
        )
        assert skipped.model is None and "not asked" in skipped.vote.abstained_reason
        assert report.stopped_on_rate_limit and "beta" in report.stop_reason

    async def test_a_provider_error_abstains_for_that_update_and_the_stage_goes_on(self) -> None:
        calls: list[int] = []
        first, second = _update("alpha"), _update("beta")
        report = await analyse(
            _updates(first, second),
            _texts(first, second),
            model=MODEL,
            version=1,
            agent_model=_failing(500, 1, calls),
        )
        failed, answered = report.per_update
        assert failed.model is not None and failed.model.outcome == "provider-error"
        assert failed.vote.level is None
        assert answered.vote.level == "high"
        assert not report.stopped_on_rate_limit

    async def test_an_answer_never_in_the_required_shape_abstains(self) -> None:
        def prose(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("It looks fine to me.")])

        update = _update()
        report = await analyse(
            _updates(update),
            _texts(update),
            model=MODEL,
            version=1,
            agent_model=FunctionModel(prose),
        )
        analysis = report.per_update[0]
        assert analysis.model is not None and analysis.model.outcome == "malformed"
        assert analysis.vote.level is None and not analysis.claims

    async def test_an_answer_cut_off_at_the_ceiling_is_asked_once_and_costed(self) -> None:
        """The seed set's first live pass lost three answers this way. pydantic-ai
        asked for each four times, every answer was cut off again, and each call
        was recorded as costing nothing. The provider billed them, and the answer
        says so."""
        calls: list[int] = []

        def cut_off(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, '{"claims": [{"kind": "remo')],
                finish_reason="length",
                usage=RequestUsage(input_tokens=12000, output_tokens=32768),
            )

        update = _update()
        report = await analyse(
            _updates(update),
            _texts(update),
            model=MODEL,
            version=1,
            agent_model=FunctionModel(cut_off),
        )
        [analysis] = report.per_update
        call = analysis.model
        assert len(calls) == 1
        assert call is not None and call.outcome == "cut-off"
        assert (call.requests, call.prompt_tokens, call.completion_tokens) == (1, 12000, 32768)
        assert analysis.vote.level is None
        assert analysis.vote.abstained_reason == (
            "the model's answer was cut off at the output ceiling (32768 tokens)"
        )

    async def test_an_answer_that_fits_exactly_is_read(self) -> None:
        """A whole tool call that ends at the ceiling is an answer, not a cut off one."""

        def exact(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name, {"claims": [REMOVAL], "stated_level": "high"}
                    )
                ],
                finish_reason="length",
            )

        update = _update()
        report = await analyse(
            _updates(update),
            _texts(update),
            model=MODEL,
            version=1,
            agent_model=FunctionModel(exact),
        )
        assert report.per_update[0].vote.level == "high"

    async def test_a_malformed_answer_records_every_request_it_took(self) -> None:
        """Prose is asked for again, up to the output retries, and each answer was billed."""

        def prose(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[TextPart("It looks fine to me.")],
                usage=RequestUsage(input_tokens=100, output_tokens=7),
            )

        update = _update()
        report = await analyse(
            _updates(update),
            _texts(update),
            model=MODEL,
            version=1,
            agent_model=FunctionModel(prose),
        )
        call = report.per_update[0].model
        assert call is not None and call.outcome == "malformed"
        assert (call.requests, call.prompt_tokens, call.completion_tokens) == (4, 400, 28)


class TestTheRecord:
    async def test_the_report_names_the_model_the_prompt_and_the_settings(self) -> None:
        report = await _one([REMOVAL])
        call = report.per_update[0].model
        assert report.model_id == MODEL and report.prompt_id == "changelog-extract/1"
        assert call is not None and call.prompt_sha256 == report.prompt_sha256
        assert call.requests == 1
        assert (call.settings.max_tokens, call.settings.thinking, call.settings.temperature) == (
            32768,
            "disabled",
            0.0,
        )

    async def test_the_report_survives_its_own_validators(self) -> None:
        """The contract re-derives every vote from the verified claims."""
        report = await _one([REMOVAL, BEHAVIOUR, FEATURE, INVENTED])
        again = ChangelogReport.model_validate(report.model_dump(by_alias=True, mode="json"))
        assert again.per_update[0].vote.level == "high"


class TestTheStage:
    async def test_the_component_answers_with_the_report_and_its_honesty_numbers(self) -> None:
        update = _update()
        answer = await C4(MODEL, agent_model=_answering([REMOVAL, INVENTED])).analyse_changelogs(
            _updates(update), _texts(update), version=3
        )
        report = answer.artefact
        assert isinstance(report, ChangelogReport) and report.version == 3
        assert answer.summary == (
            "1 update read: 1 claim verified, 1 refused; 1 voted and 0 abstained"
        )
        assert answer.notes["model_calls"] == 1 and answer.notes["refusal_rate"] == 0.5
        # The call record keeps the configured model; this names what answered.
        assert answer.notes["model_use"]["answered_by"] == ["function:respond:"]

    async def test_the_http_app_runs_the_stage_on_the_contract_types(self) -> None:
        """No notes, so no model is asked: the stage still answers, abstaining."""
        app = create_app(C4(MODEL))
        body = {
            "version": 1,
            "updates": _updates(_update(notes=None)).model_dump(by_alias=True, mode="json"),
            "notes": {},
        }
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://c4") as client:
                answer = await client.post("/stages/changelog-analysis", json=body)
        assert answer.status_code == 200, answer.text
        report = ChangelogReport.model_validate(answer.json()["artefact"])
        assert report.per_update[0].vote.level is None
