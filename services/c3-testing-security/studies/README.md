# Study runs, as they were produced

One file per run of the three way comparison, written by `python -m c3.eval`.
Kept in the repository because a number in the dissertation has to be traceable
to the run that produced it, and a run that lives only in a terminal scrollback
is a number nobody can check.

Each file carries its own epoch: the label, the commit, the benchmark and its
checkout commit, and the exact tool or model versions that answered. **Numbers
from two epochs are never averaged.** When a prompt, a rule, a model or a rule
pack changes, the next run opens a new epoch and the old file stays as it was.

The first two runs below are the scanner arm on two corpora and they disagree
completely, which is the point of having both: on CWE-22, path traversal, it
found all 133 of OWASP Benchmark's generated servlets (recall 1.000, precision
0.193) and none of the 60 real CVEs in CWE-Bench-Java, where only semgrep ran
(recall 0.000). Until 2026-10-18 this sentence said 0.773: the micro recall over
every class of the semgrep-only run of 2026-09-10, which the run with both tools
replaced the same day. No stored file holds it.

**A cost in one of these files is list price, not a bill.** It is computed from
the token counts against a published price table, so it appears whatever tier
the key was on and a run on a free tier was charged nothing at all. Which tier
a run used belongs in its epoch note beside the number.

`juliet-trained/` holds the raw evidence for that last row: the predictions
file with one row per test example, the label space the weights are meaningless
without, the run record, and the split audit. Predictions are data and are kept;
the scores in the json beside them are derived and can be recomputed.

The benchmarks themselves are not here. OWASP Benchmark is GPL-2.0, so it is
cloned beside the workspace at evaluation time and its commit is recorded in
the epoch rather than its contents being copied into this repository.

## What the stored files lack, and from when it is fixed

Found by the review of 2026-10-17 (TODO E-4). A stored run stays as it was
written: each gap below is fixed for the runs after it, and the files keep theirs.

- **The scanner's version** in epochs 4 and 10 (`owasp-scanner-trained.json`,
  `owasp-three-way-deepseek.json`) reads `semgrep Installed 66 packages in ...`,
  the line `uvx` printed after the version. The version has been read from a
  line that looks like one since `68d2aab`, so epoch 11 on carries it.
- **`split_seed`** is empty in every detection file. There was no seed to keep: a
  benchmark is read in its own order and a slice is its first rows, so the same
  slice comes back every run. Runs from 2026-10-18 on say `"none"`, and the note
  says how much was read and how.
- **Macro F1 leaves out findings in classes a slice does not label.** `TABLES.md`
  counts them beside each arm and says which scores are class blind.
- **`juliet-trained.json` carries no commit, date or weights hash.** Its files came
  into the repository with `4621cb7` on 2026-09-13. `juliet-trained/split-audit.json`,
  written by `python -m c3.ml.audit` at `1d54977`, now holds what can be checked:
  the weights' sha256, that the folder holding them has this run's own run record,
  labels and predictions, and the split itself, 758, 78 and 80 families with none
  in two splits, every row where the rule puts it, and the 14,094 predictions over
  exactly the 80 test families.
- **DeepSeek runs record their cost as null** (epochs 10 and 11): the price table
  pydantic-ai reads, `genai-prices` 0.1.1, did not know `deepseek-flash`, the name
  DeepSeek's answers carry. 0.1.13 does, at the list prices DeepSeek publishes, so
  detection runs from 2026-10-18 on carry a cost. It models DeepSeek's peak hours by time of
  day only, so a run on a weekend is priced as an upper bound. The healing pipeline's
  stages record tokens and never a cost, so a heal epoch's cost is worked out from its
  tokens, and its row says so.

## Runs

| File | Epoch | What it measures |
|---|---|---|
| `owasp-scanner.json` | epoch-2 scanner arm, both tools | semgrep 1.176.1 and findsecbugs 4.10.4 over OWASP Benchmark 1.2, the zero cost baseline the model arms have to beat |
| `cwe-bench-scanner.json` | epoch-2 scanner on real CVEs | semgrep over 12 CWE-Bench-Java projects at their buggy commits: 60 real weaknesses, none found |
| `owasp-scanner-trained.json` | epoch-4 scanner vs trained | both arms over all 2,740 OWASP servlets. The trained arm flagged every method it was shown; written before `unitsExamined` existed, so that fact lives in the guide rather than in the file |
| `healing-checkpoint2.json` | epoch-5 checkpoint 2, **scored from a report written by hand** | the first statement of the 50 point gap. Its report, `heals/checkpoint-2.json`, was written rather than produced by a run (found 2026-10-17), and its 66.67 percent rule decided share counts a referee verdict no model gave. Kept as it was; superseded by epoch 14, the next two rows |
| `healing-tracker-sprint2.json` | epoch-12 the healing loop on generated code | the first heal through the guard on an app this platform generated: the Task Tracker's sprint 2 change (`p_ea2157d82c6a`, test version 4, 2026-09-26). Six failures, all called brittle by the trace; six repairs produced and none accepted, naive convergence 100 percent against strict 0, every refusal `still-failing`: none of the six repairs worked. Scored with `--rejudge`, because the report was written seven minutes before the defect 22 fix (`55c41e1`) and stores those six as `kills-no-mutant`, the caught cheat; the row says six names changed. Classification 5 of 6: US-1 AC-1-5, a correct test of an empty name, was called brittle. The other five were written wrong from the start (three call `app.request`, two assume an id the test made up) and are labelled brittle because their fix is in the test |
| `heals-tracker-sprint2/` | epoch-12 the report behind it | the run's `heal-report` artefact at test version 4, exported as stored. The row's commit is the last before the report was written (20:20 +05:30); the server's start was not recorded. C3 ran `deepseek:deepseek-flash`, as the guide recorded it; the run row predates the model column. Labels proposed from the stored records and confirmed by the owner, 2026-10-18 |
| `healing-tracker-seeded.json` | epoch-13 a seeded regression, flagged and never healed | the same project at test version 5, with a data loss bug seeded into code version 3 on purpose. Five failures: three flagged as regressions by `trace-unchanged` and never repaired, and two of C2's contract tests left undecided because they trace to nothing. All five are labelled regression, the seed; classification 3 of 5, and 3 of the 3 it decided |
| `heals-tracker-seeded/` | epoch-13 the report behind it | the run's `heal-report` artefact at test version 5, exported as stored; the row's commit is the last before it was written (22:09 +05:30). Labelled as epoch 12's |
| `healing-checkpoint2-scripted.json` | epoch-14 checkpoint 2 through the guard | the same pair as the guard's own record: checkpoint 2's two hand written answers through the real install, runner, classifier and guard, with no model asked. Naive convergence 100 percent against strict 50, so the guard caught 50 points; all 4 failures classified by the trace alone; 2 seeded regressions flagged and never healed. Still an illustration over 2 repairs |
| `heals-scripted/` | epoch-14 the reports behind it | one run per answer, identical but for the answer, written by `python -m c3.eval.repair_proof scripted:<honest or weakened> --with-regression --studies studies/heals-scripted` at `f5b4236` |
| `healing-pipeline-task-tracker.json` | epoch-15 a pipeline run through the guard | the first heal report a full pipeline run produced: the Task Tracker's change from a task's title to its name (TODO E-2, first run). No stale test failed; the one failure was a correct test, which the trace rule called brittle, and the guard refused the repair that rewrote it to accept the bug. Naive convergence 100 percent against strict 0 over one repair, and classification 0 of 1, a regression called brittle. The refusal is `kills-no-mutant` because no mutant could be made on the type-only lines that changed. An illustration of each, not a result |
| `heals-pipeline/` | epoch-15 the report behind it | the run's `heal-report` artefact at test version 2, exported as stored (project `p_d99cdec82620`, run `8b5d9f8f`, 2026-10-18); C3 ran `deepseek:deepseek-flash` with thinking at high, as the run recorded it, on the server side of `290a87f`. Labelled by the owner |
| `healing-pipeline-to-do.json` | epoch-16 a pipeline run on a renamed entity | the Task Tracker's sprint 3 change, from a task to a to-do (TODO E-2, second run), and the first truly stale tests a pipeline run produced. Nine failures, all called brittle by the trace; one repair accepted, naive and strict convergence 11.11 percent. The accepted repair is a cheat: US-7 AC-7-2, a correct test written at that version, was rewritten to expect the bug, and the guard accepted it on a mutant of an import, so the row counts one regression healed. The eight `no-repair-produced` are not the model's silence: it wrote 16 drafts, and the draft check refused every one because their files declare criteria not yet written. Classification 7 of 9, both errors regressions called brittle. The run that found TODO E-25, E-27, E-28 and E-29, all fixed after it; an illustration of each, not a result |
| `heals-pipeline-to-do/` | epoch-16 the report behind it | the run's `heal-report` artefact at test version 3, exported as stored (project `p_d99cdec82620`, run `81cd347d`, 2026-10-18); C3 ran `deepseek:deepseek-flash` with thinking at high on the server side of `830d03e`, a model DeepSeek's page names DeepSeek-V4.1-Flash-1017. Its cost is not recorded: the pipeline's stages record tokens and not cost (corrected 2026-10-19; this said the server had been started before `5de9bea`, which prices the detection study's answers only). Labels proposed from the stored records and confirmed by the owner, 2026-10-18 |
| `healing-pipeline-to-do-rerun.json` | epoch-17 the renamed entity run again, after the fixes | the same nine failures at test version 4, on the same code, after TODO E-25 and E-27 to E-29. US-7 AC-7-2 was flagged by `written-after-change` and never repaired; the eight others reached the guard, and two repairs were accepted: US-1 AC-1-1, a renamed route with every assertion kept, the first honest heal of a stale test on generated code; and US-4 AC-4-2, which still sends and checks `title`, passing only because the generated API stores what it is sent (TODO E-26). Naive convergence 100 percent against strict 25, and the 75 points are not cheats caught: all six refusals are `still-failing` because each repair closed a brace it never opened, so its file did not parse (TODO E-30); read as diffs, five of the six are otherwise correct repairs. Classification 8 of 9, the miss US-6 AC-6-3, a carried test whose code is also wrong (TODO E-7). An illustration, not a result |
| `heals-pipeline-to-do-rerun/` | epoch-17 the report behind it | the run's `heal-report` artefact at test version 4, exported as stored (project `p_d99cdec82620`, run `81cd347d` regenerating on changes requested at the test review, 2026-10-18 19:22 to 19:31 UTC); C3 ran `deepseek:deepseek-flash` with thinking at high on the server side of `691c6ed`. The run records tokens and not cost: 27,554 in and 104,256 out over the two stages that asked the model, about $0.07 at DeepSeek's off peak list prices. Labels as epoch 16's, the same nine tests with the same causes, confirmed by the owner, 2026-10-19 |
| `owasp-scanner-llm.json` | epoch-11 the ensemble ablation | the same 200 files without the trained arm: merged 0.524 against the prompted arm's 0.752, so the union and not the degenerate arm is what loses. Also a second complete pass of the prompted arm, which bounds its run to run variance at 0.038 macro F1 |
| `owasp-three-way-deepseek.json` | epoch-10 all three arms, complete | the same 200 files with a provider that has no daily cap, so every arm finished: llm macro F1 0.790 and the best of the three, scanner 0.646, trained 0.313 flagging everything, merged 0.510 and still below its best part. Overturns epoch 9, whose prompted arm had read a third of the corpus |
| `owasp-three-way.json` | epoch-9 all three arms | 200 OWASP files, 128 real weaknesses, every arm over the same list: scanner macro F1 0.646, trained 0.313 having flagged 100 percent of what it examined, llm 0.303 over a pass a quota cut short, merged 0.566 and below the free arm it was added to |
| `owasp-llm-200.json`, `owasp-llm-50-partial.json` | epoch-9 prompted arm, quota limited | two attempts to complete the arm's pass over the study's file list, stopped at the first rate limit by the rule this project runs under. Precision 0.947 and 1.000; recall not measurable, since each is computed against the whole slice while the arm read part of it |
| `owasp-llm-live-slice.json` | epoch-6 prompted arm, live | gemini-3.5-flash-lite over 20 of 2,740 OWASP files: precision 1.000, recall 0.824, one finding refused for evidence that did not resolve. An illustration, not a result: the same slice run twice returned 0.765 then 0.824 |
| `heals-live-gemini/` | epoch-6 repair through the guard | the checkpoint 2 scenario answered by a real model under both prompt shapes, both accepted, produced by `python -m c3.eval.repair_proof` |
| `juliet-trained.json` | epoch-3 trained arm | GraphCodeBERT fine tuned on Juliet, detection F1 0.992 and classification macro F1 0.652 on a family split test set |
