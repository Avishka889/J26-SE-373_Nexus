"""The probe names what went wrong, instead of reprinting the provider."""

import pytest
from c2.probe import diagnose


class TestItNamesWhatWentWrong:
    @pytest.mark.parametrize(
        ("message", "expected_fragment"),
        [
            ("404 model_not_found", "decommissioned"),
            ("`tool_choice` is not supported", "forced tool call"),
            ("Request too large: tokens per minute", "larger than this tier allows"),
            ("Invalid API key provided", "no key for this provider"),
        ],
    )
    def test_a_real_failure_is_recognised(self, message: str, expected_fragment: str) -> None:
        assert expected_fragment in diagnose(message)

    def test_an_unrecognised_message_says_so_rather_than_guessing(self) -> None:
        assert diagnose("something entirely new") == "unrecognised failure, read the message above"
