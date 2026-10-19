# Heal reports, and what a person decided they really were

Stored heal reports, read by `python -m c3.eval --healing`. One file per run.

`labels.json` is the ground truth: a test id mapped to what a person decided
the failure actually was, `brittle` or `regression`. It is hand written and has
to be, because the alternative is scoring the classifier against its own
verdicts, which measures its consistency rather than its correctness.

**A label is a judgement about a failure, not a correction of the report.** The
report stays exactly as the run produced it. That separation is what lets the
same reports be re-scored later against better labels without anything being
rewritten.

## What is here

| File | What it is |
|---|---|
| `checkpoint-2.json` | **Written by hand, not produced by a run.** Meant as the pair the headline contribution rests on: one repair accepted through the guard and one refused for weakening its assertion, plus a regression flagged and never healed |
| `labels.json` | What each of those three failures really was |

Checkpoint 2's two repairs are both genuinely brittle: requirement R-4 changed
its rounding and R-7 changed its threshold, so the tests encoded behaviour that
had moved. The third traces to an artefact that did not change, so the test is
right and the code is not.

**Found 2026-10-17: `checkpoint-2.json` is not a run's output.** Its check texts
("the suite is green", "killed 2 of 3 injected mutants") are not strings the
guard writes, its second attempt is marked `model-referee` on a trace the rule
decides alone, and `killedMutantIds` is empty where its own check says two of
three. Nothing in the code writes it. It stays as it was, because stored files
are never rewritten, and it is no longer the record: the checkpoint 2 scenario
run through the guard is `../heals-scripted/`, epoch 14.
