"""The probe's verdicts, on scripted answers rather than a provider.

Each test hands the probe an answer a real model could give and checks the
verdict it reaches. The one that matters most is the invented quote: a model
that makes up a sentence the notes do not contain is the failure the changelog
signal's check exists to refuse, and the probe must call it unusable before any
evaluation token is spent on it.
"""

from typing import Any

import pytest
from c4 import probe
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

REMOVAL = {
    "kind": "removal",
    "symbols": ["Client.connectLegacy"],
    "quote": "Removed `Client.connectLegacy()`; use `Client.connect()` instead.",
    "version": "2.0.0",
}
DEPRECATION = {
    "kind": "deprecation",
    "symbols": ["Pool.drain"],
    "quote": "Deprecated `Pool.drain()`; it will be removed in 3.0.",
    "version": "1.5.0",
}


def _answering(claims: list[dict[str, Any]], calls: list[int] | None = None) -> FunctionModel:
    def respond(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if calls is not None:
            calls.append(1)
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name, {"claims": claims, "stated_level": "high"})
            ]
        )

    return FunctionModel(respond)


async def test_real_quotes_in_the_window_and_the_removal_found_is_suitable(capsys) -> None:
    code = await probe.probe("scripted", agent_model=_answering([REMOVAL, DEPRECATION]))
    assert code == 0
    assert "SUITABLE" in capsys.readouterr().out


async def test_the_ceiling_printed_is_the_one_the_request_carries(capsys) -> None:
    """DeepSeek's ceiling travels in the body; the probe prints it from there."""
    await probe.probe("deepseek:deepseek-flash", agent_model=_answering([REMOVAL, DEPRECATION]))
    assert "ceiling    32768" in capsys.readouterr().out


async def test_an_invented_quote_is_unusable(capsys) -> None:
    invented = {**REMOVAL, "quote": "Removed Client.connectLegacy() entirely."}
    code = await probe.probe("scripted", agent_model=_answering([invented]))
    out = capsys.readouterr().out
    assert code == 1
    assert "UNUSABLE" in out and "not in the notes" in out


async def test_a_symbol_its_quote_does_not_contain_is_unusable(capsys) -> None:
    misnamed = {**DEPRECATION, "symbols": ["Pool.close"]}
    code = await probe.probe("scripted", agent_model=_answering([REMOVAL, misnamed]))
    assert code == 1
    assert "symbol not in its quote" in capsys.readouterr().out


async def test_reaching_below_the_window_is_workable(capsys) -> None:
    decoy = {
        "kind": "removal",
        "symbols": [],
        "quote": "Removed the undocumented `debug` flag.",
        "version": "1.4.2",
    }
    code = await probe.probe("scripted", agent_model=_answering([REMOVAL, decoy]))
    out = capsys.readouterr().out
    assert code == 0
    assert "WORKABLE" in out and "outside the window" in out


async def test_missing_the_removal_is_workable(capsys) -> None:
    code = await probe.probe("scripted", agent_model=_answering([DEPRECATION]))
    out = capsys.readouterr().out
    assert code == 0
    assert "WORKABLE" in out and "missed" in out


async def test_a_rate_limit_is_asked_once_and_means_stop(capsys) -> None:
    calls: list[int] = []

    def limited(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        raise ModelHTTPError(status_code=429, model_name="scripted", body={"error": "rate limit"})

    code = await probe.probe("scripted", agent_model=FunctionModel(limited))
    out = capsys.readouterr().out
    assert code == 2
    assert "rate limited: stop rather than retry" in out
    assert calls == [1]


def test_the_model_is_shown_the_decoy_so_reaching_for_it_is_possible() -> None:
    assert "## 1.4.2" in probe.prompt()


@pytest.mark.parametrize("claims", [[], [DEPRECATION]])
def test_the_check_never_credits_a_removal_that_was_not_claimed(claims) -> None:
    from c4.risk.claims import ChangelogAnswer

    assert not probe.check(ChangelogAnswer(claims=claims, stated_level="low")).found_removal
