"""The provider probe's readings of real failures.

Every message below is verbatim from a run. The point of the probe is that these
four mechanisms are indistinguishable at a glance and each one cost a real run
to identify, so the mapping from message to meaning is worth pinning.
"""

import pytest
from c1.probe import diagnose

#: Left column verbatim from a provider. Right column is what it means for C1.
REAL_FAILURES = [
    (
        "status_code: 404, body: {'error': {'message': 'The model "
        "`llama-3.3-70b-versatile` does not exist or you do not have access to it.', "
        "'code': 'model_not_found'}}",
        "decommissioned",
    ),
    (
        "status_code: 400, body: {'error': {'message': '`tool calling` is not supported "
        "with this model', 'param': 'tool calling'}}",
        "cannot call tools",
    ),
    (
        "status_code: 413, body: {'error': {'message': 'Request too large for model "
        "`openai/gpt-oss-120b` on tokens per minute (TPM): Limit 8000, Requested 11605'}}",
        "larger than this tier allows per minute",
    ),
    (
        "status_code: 400, body: {'error': {'message': 'You have reached your specified "
        "API usage limits. You will regain access on 2026-09-01 at 00:00 UTC.'}}",
        "spend cap",
    ),
]


class TestItNamesWhatWentWrong:
    @pytest.mark.parametrize(
        ("message", "expected"), REAL_FAILURES, ids=["decommissioned", "no-tools", "tpm", "cap"]
    )
    def test_a_real_failure_is_recognised(self, message: str, expected: str) -> None:
        assert expected in diagnose(message)

    def test_the_token_limit_is_not_read_as_ordinary_rate_limiting(self) -> None:
        # These need different actions. A per minute ceiling smaller than one
        # request cannot be waited out; ordinary rate limiting can.
        tpm = diagnose("on tokens per minute (TPM): Limit 8000, Requested 11605")
        assert "per minute" in tpm
        assert "check whether" not in tpm, "it must not fall through to the vaguer reading"

    def test_a_missing_extra_is_told_apart_from_a_missing_key(self) -> None:
        extra = diagnose(
            "Please install the `mistral` package, you can use the `mistral` optional group"
        )
        key = diagnose("Set the `ANTHROPIC_API_KEY` environment variable or pass api key")
        assert "extra is not installed" in extra
        assert "no key" in key
        assert extra != key

    def test_an_unrecognised_message_says_so_rather_than_guessing(self) -> None:
        # A probe that invents a diagnosis is worse than one that admits it does
        # not know: the reader stops looking at the message that matters.
        assert "unrecognised" in diagnose("something nobody has seen before")
