"""The repair proof's scripted lane: checkpoint 2's two answers, asked of no one.

The lane exists so the stored checkpoint 2 report is the guard's own record of
a run rather than a file written by hand. That holds only if a scripted answer
reaches the guard as exactly the file the checkpoint 2 tests write, in either
shape, which is what these check. What the guard then does with each answer is
checkpoint 2's own business (`test_heal.py`), with the same two answers.
"""

import sys

import pytest
from c3.eval import repair_proof
from c3.eval.repair_proof import HONEST, STALE, SUITE, WEAKENED, failing_report, scripted_repairer
from c3.heal.repair import repair


@pytest.mark.parametrize("shape", ["minimal", "whole-file"])
@pytest.mark.parametrize("answer", [HONEST, WEAKENED], ids=["honest", "weakened"])
async def test_a_scripted_answer_arrives_as_the_file_checkpoint_2_writes(answer, shape) -> None:
    stale = failing_report().suites[0].cases[0]

    outcome = await repair(
        scripted_repairer(answer, shape=shape),
        stale,
        source=STALE,
        path=SUITE,
        shape=shape,
    )

    assert outcome.content == answer
    # Read off the answer rather than the request, so this also says the lane
    # answers in the shape it was asked for, as a model would.
    assert outcome.shape == shape


def test_an_unknown_scripted_answer_is_refused_before_anything_installs(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(sys, "argv", ["repair_proof", "scripted:clever"])

    assert repair_proof.main() == 64
    assert "scripted:honest or scripted:weakened" in capsys.readouterr().out
