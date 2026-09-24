# Study runs, as they were produced

One file per run of the three way comparison, written by `python -m c3.eval`.
Kept in the repository because a number in the dissertation has to be traceable
to the run that produced it, and a run that lives only in a terminal scrollback
is a number nobody can check.

Each file carries its own epoch: the label, the commit, the benchmark and its
checkout commit, and the exact tool or model versions that answered. **Numbers
from two epochs are never averaged.** When a prompt, a rule, a model or a rule
pack changes, the next run opens a new epoch and the old file stays as it was.

The two runs below are the same arm on two corpora and they disagree
completely, which is the point of having both: 0.773 recall on generated
servlets and 0.000 on real CVEs of the same weakness class.

**A cost in one of these files is list price, not a bill.** It is computed from
the token counts against a published price table, so it appears whatever tier
the key was on and a run on a free tier was charged nothing at all. Which tier
a run used belongs in its epoch note beside the number.

`juliet-trained/` holds the raw evidence for that last row: the predictions
file with one row per test example, the label space the weights are meaningless
without, and the run record. Predictions are data and are kept; the scores in
the json beside them are derived and can be recomputed.

The benchmarks themselves are not here. OWASP Benchmark is GPL-2.0, so it is
cloned beside the workspace at evaluation time and its commit is recorded in
the epoch rather than its contents being copied into this repository.

## Runs

| File | Epoch | What it measures |
|---|---|---|
| `owasp-scanner.json` | epoch-2 scanner arm, both tools | semgrep 1.176.1 and findsecbugs 4.10.4 over OWASP Benchmark 1.2, the zero cost baseline the model arms have to beat |
| `cwe-bench-scanner.json` | epoch-2 scanner on real CVEs | semgrep over 12 CWE-Bench-Java projects at their buggy commits: 60 real weaknesses, none found |
| `owasp-scanner-trained.json` | epoch-4 scanner vs trained | both arms over all 2,740 OWASP servlets. The trained arm flagged every method it was shown; written before `unitsExamined` existed, so that fact lives in the guide rather than in the file |
| `healing-checkpoint2.json` | epoch-5 checkpoint 2 | the guard caught 50 points: naive convergence 100 percent against strict 50 percent on the pair the headline contribution rests on |
| `owasp-scanner-llm.json` | epoch-11 the ensemble ablation | the same 200 files without the trained arm: merged 0.524 against the prompted arm's 0.752, so the union and not the degenerate arm is what loses. Also a second complete pass of the prompted arm, which bounds its run to run variance at 0.038 macro F1 |
| `owasp-three-way-deepseek.json` | epoch-10 all three arms, complete | the same 200 files with a provider that has no daily cap, so every arm finished: llm macro F1 0.790 and the best of the three, scanner 0.646, trained 0.313 flagging everything, merged 0.510 and still below its best part. Overturns epoch 9, whose prompted arm had read a third of the corpus |
| `owasp-three-way.json` | epoch-9 all three arms | 200 OWASP files, 128 real weaknesses, every arm over the same list: scanner macro F1 0.646, trained 0.313 having flagged 100 percent of what it examined, llm 0.303 over a pass a quota cut short, merged 0.566 and below the free arm it was added to |
| `owasp-llm-200.json`, `owasp-llm-50-partial.json` | epoch-9 prompted arm, quota limited | two attempts to complete the arm's pass over the study's file list, stopped at the first rate limit by the rule this project runs under. Precision 0.947 and 1.000; recall not measurable, since each is computed against the whole slice while the arm read part of it |
| `owasp-llm-live-slice.json` | epoch-6 prompted arm, live | gemini-3.5-flash-lite over 20 of 2,740 OWASP files: precision 1.000, recall 0.824, one finding refused for evidence that did not resolve. An illustration, not a result: the same slice run twice returned 0.765 then 0.824 |
| `heals-live-gemini/` | epoch-6 repair through the guard | the checkpoint 2 scenario answered by a real model under both prompt shapes, both accepted, produced by `python -m c3.eval.repair_proof` |
| `juliet-trained.json` | epoch-3 trained arm | GraphCodeBERT fine tuned on Juliet, detection F1 0.992 and classification macro F1 0.652 on a family split test set |
