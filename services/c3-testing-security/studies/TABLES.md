# Detection tables

Generated from the stored runs by `python -m c3.eval --tables`. Every number here is in a file beside it; nothing is computed on the way out.

## Provenance

Every table below names its epoch. This is where an epoch names its run.

| epoch | when | commit | target | slice | file |
|---|---|---|---|---|---|
| `epoch-2 scanner both tools` | 2026-09-09 | `870e8e0` | OWASP Benchmark 1.2 | 2740 files of 2740 | `owasp-scanner-both.json` |
| `epoch-2 scanner arm, both tools` | 2026-09-09 | `d01e66e` | OWASP Benchmark 1.2 | 2740 files of 2740 | `owasp-scanner.json` |
| `epoch-2 scanner on real CVEs` | 2026-09-10 | `d535cac` | CWE-Bench-Java, 12 projects | 43551 files | `cwe-bench-scanner.json` |
| `epoch-4 scanner and trained on OWASP` | 2026-09-13 | `3f341d1` | OWASP Benchmark 1.2 | 2740 files of 2740 | `owasp-scanner-trained.json` |
| `epoch-6-llm-live` | 2026-09-25 | `ad960bc` | OWASP Benchmark 1.2 | 20 files of 2740 | `owasp-llm-live-slice.json` |
| `epoch-9-three-way` | 2026-09-25 | `9d513e0` | OWASP Benchmark 1.2 | 200 files of 2740 | `owasp-three-way.json` |
| `epoch-9-llm-complete` | 2026-09-26 | `e57da5e` | OWASP Benchmark 1.2 | 200 files of 2740 | `owasp-llm-200.json` |
| `probe-quota` | 2026-09-26 | `e57da5e` | OWASP Benchmark 1.2 | 50 files of 2740 | `owasp-llm-50-partial.json` |
| `epoch-10-three-way-deepseek` | 2026-09-26 | `657bc62` | OWASP Benchmark 1.2 | 200 files of 2740 | `owasp-three-way-deepseek.json` |
| `epoch-11-scanner-and-llm` | 2026-09-26 | `094bc06` | OWASP Benchmark 1.2 | 200 files of 2740 | `owasp-scanner-llm.json` |

## The arms, by epoch

One table per epoch. Numbers from two epochs are never put in one table, because a rule, a model or a corpus changed between them.

### epoch-2 scanner both tools

OWASP Benchmark 1.2, 2740 files of 2740, 1415 real weaknesses. Commit `870e8e0`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scanner | `semgrep 1.176.1 + findsecbugs 4.10.4` | not reported | not reported | 0.629 | 8,643 | 0 | n/a | 1,599 | 0 | 0.0000 | no |  |

### epoch-2 scanner arm, both tools

OWASP Benchmark 1.2, 2740 files of 2740, 1415 real weaknesses. Commit `d01e66e`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scanner | `semgrep 1.176.1 + findsecbugs 4.10.4` | not reported | not reported | 0.629 | 8,643 | 0 | n/a | 1,664 | 0 | 0.0000 | no |  |

### epoch-2 scanner on real CVEs

CWE-Bench-Java, 12 projects, 43551 files, 60 real weaknesses. Commit `d535cac`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scanner | `semgrep 1.176.1` | not reported | not reported | 0.000 | 227 | 0 | n/a | 1,455 | 0 | 0.0000 | no | **incomplete** |

Marked **incomplete**, and the mark is the point:
- `scanner` did not finish its pass. findsecbugs: spotbugs failed and left no report: with the -e switch.
[ERROR] Re-run Maven using the -X switch to enable full debug logging.
[ERROR] 
[ERROR] For

### epoch-4 scanner and trained on OWASP

OWASP Benchmark 1.2, 2740 files of 2740, 1415 real weaknesses. Commit `3f341d1`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scanner | `semgrep Installed 66 packages in 695ms + findsecbugs 4.10.4` | 0.163 | 0.997 | 0.629 | 8,643 | 0 | n/a | 1,759 | 0 | 0.0000 | no |  |
| trained | `microsoft/graphcodebert-base fine tuned, c3-juliet` | 0.194 | 1.000 | 0.209 | 7,295 | 0 | n/a | 10,715 | 0 | 0.0000 | yes |  |
| merged | `semgrep Installed 66 packages in 695ms + findsecbugs 4.10.4 + microsoft/graphcodebert-base fine tuned, c3-juliet` | 0.089 | 1.000 | 0.526 | 15,938 | 0 | n/a | 12,475 | 0 | 0.0000 | no |  |

### epoch-6-llm-live

OWASP Benchmark 1.2, 20 files of 2740, 17 real weaknesses. Commit `ad960bc`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| llm | `google:gemini-3.5-flash-lite` | 1.000 | 0.824 | 0.691 | 14 | 1 | n/a | 17 | 31,337 | 0.0140 | no |  |

### epoch-9-three-way

OWASP Benchmark 1.2, 200 files of 2740, 128 real weaknesses. Commit `9d513e0`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scanner | `semgrep 1.178.0 + findsecbugs 4.10.4` | 0.151 | 1.000 | 0.646 | 846 | 0 | 15% | 1,594 | 0 | 0.0000 | no |  |
| trained | `microsoft/graphcodebert-base fine tuned, c3-juliet` | 0.318 | 1.000 | 0.313 | 402 | 0 | 100% | 474 | 0 | 0.0000 | yes | **degenerate** |
| llm | `google:gemini-3.5-flash-lite` | 0.865 | 0.250 | 0.303 | 37 | 4 | n/a | 173 | 125,104 | 0.0506 | no | **incomplete** |
| merged | `semgrep 1.178.0 + findsecbugs 4.10.4 + microsoft/graphcodebert-base fine tuned, c3-juliet + google:gemini-3.5-flash-lite` | 0.102 | 1.000 | 0.566 | 1,259 | 4 | 22% | 2,241 | 125,104 | 0.0506 | no | **incomplete** |

Marked **incomplete**, and the mark is the point:
- `llm` did not finish its pass. chunk 108 of 108: ModelHTTPError: status_code: 429, model_name: gemini-3.5-flash-lite, body: {'error': {'code': 429, 'message': 'You exceeded your current quota
- `merged` did not finish its pass. chunk 108 of 108: ModelHTTPError: status_code: 429, model_name: gemini-3.5-flash-lite, body: {'error': {'code': 429, 'message': 'You exceeded your current quota

Marked **degenerate**: `trained` flagged 402 of the 402 units it examined. Its recall is an artefact of that and is not a result.

### epoch-9-llm-complete

OWASP Benchmark 1.2, 200 files of 2740, 128 real weaknesses. Commit `e57da5e`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| llm | `google:gemini-3.5-flash-lite` | 0.947 | 0.281 | 0.344 | 38 | 5 | n/a | 84 | 100,757 | 0.0436 | no | **incomplete** |

Marked **incomplete**, and the mark is the point:
- `llm` did not finish its pass. stopped after chunk 31 of 108: the provider refused with a rate limit and this run does not retry. 77 chunks were never attempted

### probe-quota

OWASP Benchmark 1.2, 50 files of 2740, 45 real weaknesses. Commit `e57da5e`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| llm | `google:gemini-3.5-flash-lite` | 1.000 | 0.489 | 0.455 | 22 | 3 | n/a | 29 | 55,203 | 0.0241 | no | **incomplete** |

Marked **incomplete**, and the mark is the point:
- `llm` did not finish its pass. stopped after chunk 17 of 21: the provider refused with a rate limit and this run does not retry. 4 chunks were never attempted

### epoch-10-three-way-deepseek

OWASP Benchmark 1.2, 200 files of 2740, 128 real weaknesses. Commit `657bc62`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scanner | `semgrep Installed 66 packages in 129ms + findsecbugs 4.10.4` | 0.151 | 1.000 | 0.646 | 846 | 0 | 15% | 1,750 | 0 | 0.0000 | no |  |
| trained | `microsoft/graphcodebert-base fine tuned, c3-juliet` | 0.318 | 1.000 | 0.313 | 402 | 0 | 100% | 557 | 0 | 0.0000 | yes | **degenerate** |
| llm | `deepseek:deepseek-flash` | 0.689 | 0.883 | 0.790 | 164 | 18 | n/a | 201 | 338,138 | not reported | no |  |
| merged | `semgrep Installed 66 packages in 129ms + findsecbugs 4.10.4 + microsoft/graphcodebert-base fine tuned, c3-juliet + deepseek:deepseek-flash` | 0.096 | 1.000 | 0.510 | 1,340 | 18 | 24% | 2,508 | 338,138 | not reported | no |  |

Marked **degenerate**: `trained` flagged 402 of the 402 units it examined. Its recall is an artefact of that and is not a result.

### epoch-11-scanner-and-llm

OWASP Benchmark 1.2, 200 files of 2740, 128 real weaknesses. Commit `094bc06`.

| arm | model | precision | recall | macro F1 | findings | refused | flagged | seconds | tokens | cost | offline | |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scanner | `semgrep 1.178.0 + findsecbugs 4.10.4` | 0.151 | 1.000 | 0.646 | 846 | 0 | 15% | 1,596 | 0 | 0.0000 | no |  |
| llm | `deepseek:deepseek-flash` | 0.614 | 0.906 | 0.752 | 189 | 14 | n/a | 216 | 341,565 | not reported | no |  |
| merged | `semgrep 1.178.0 + findsecbugs 4.10.4 + deepseek:deepseek-flash` | 0.134 | 1.000 | 0.524 | 957 | 14 | 17% | 1,811 | 341,565 | not reported | no |  |

## By weakness class

#### epoch-2 scanner both tools: F1 by weakness class

| CWE | support | scanner |
|---|---|---|
| CWE-89 | 272 | 0.535 |
| CWE-327 | 259 | 0.731 |
| CWE-79 | 246 | 0.384 |
| CWE-330 | 218 | 1.000 |
| CWE-22 | 133 | 0.324 |
| CWE-78 | 126 | 0.575 |
| CWE-501 | 83 | 0.826 |
| CWE-614 | 36 | 0.667 |
| CWE-90 | 27 | 0.635 |
| CWE-643 | 15 | 0.612 |

#### epoch-2 scanner arm, both tools: F1 by weakness class

| CWE | support | scanner |
|---|---|---|
| CWE-89 | 272 | 0.535 |
| CWE-327 | 259 | 0.731 |
| CWE-79 | 246 | 0.384 |
| CWE-330 | 218 | 1.000 |
| CWE-22 | 133 | 0.324 |
| CWE-78 | 126 | 0.575 |
| CWE-501 | 83 | 0.826 |
| CWE-614 | 36 | 0.667 |
| CWE-90 | 27 | 0.635 |
| CWE-643 | 15 | 0.612 |

#### epoch-2 scanner on real CVEs: F1 by weakness class

| CWE | support | scanner |
|---|---|---|
| CWE-22 | 60 | 0.000 |

#### epoch-4 scanner and trained on OWASP: F1 by weakness class

| CWE | support | scanner | trained | merged |
|---|---|---|---|---|
| CWE-89 | 272 | 0.535 | 0.596 | 0.403 |
| CWE-327 | 259 | 0.731 | 0.000 | 0.731 |
| CWE-79 | 246 | 0.384 | 0.153 | 0.289 |
| CWE-330 | 218 | 1.000 | 0.000 | 1.000 |
| CWE-22 | 133 | 0.324 | 0.015 | 0.323 |
| CWE-78 | 126 | 0.575 | 0.586 | 0.426 |
| CWE-501 | 83 | 0.826 | 0.000 | 0.826 |
| CWE-614 | 36 | 0.667 | 0.000 | 0.667 |
| CWE-90 | 27 | 0.635 | 0.397 | 0.286 |
| CWE-643 | 15 | 0.612 | 0.344 | 0.306 |

#### epoch-6-llm-live: F1 by weakness class

| CWE | support | llm |
|---|---|---|
| CWE-327 | 4 | 0.667 |
| CWE-78 | 4 | 1.000 |
| CWE-22 | 3 | 0.500 |
| CWE-79 | 2 | 0.667 |
| CWE-89 | 2 | 1.000 |
| CWE-501 | 1 | 0.000 |
| CWE-90 | 1 | 1.000 |

#### epoch-9-three-way: F1 by weakness class

| CWE | support | scanner | trained | llm | merged |
|---|---|---|---|---|---|
| CWE-89 | 30 | 0.682 | 0.767 | 0.462 | 0.484 |
| CWE-327 | 23 | 0.691 | 0.000 | 0.296 | 0.691 |
| CWE-330 | 23 | 1.000 | 0.000 | 0.467 | 1.000 |
| CWE-79 | 20 | 0.444 | 0.333 | 0.182 | 0.339 |
| CWE-78 | 12 | 0.615 | 0.720 | 0.444 | 0.453 |
| CWE-22 | 11 | 0.301 | 0.000 | 0.375 | 0.297 |
| CWE-501 | 3 | 0.667 | 0.000 | 0.000 | 0.667 |
| CWE-614 | 3 | 0.667 | 0.000 | 0.000 | 0.667 |
| CWE-90 | 3 | 0.750 | 1.000 | 0.500 | 0.500 |

#### epoch-9-llm-complete: F1 by weakness class

| CWE | support | llm |
|---|---|---|
| CWE-89 | 30 | 0.488 |
| CWE-327 | 23 | 0.414 |
| CWE-330 | 23 | 0.000 |
| CWE-79 | 20 | 0.182 |
| CWE-78 | 12 | 0.375 |
| CWE-22 | 11 | 0.842 |
| CWE-501 | 3 | 0.000 |
| CWE-614 | 3 | 0.000 |
| CWE-90 | 3 | 0.800 |

#### probe-quota: F1 by weakness class

| CWE | support | llm |
|---|---|---|
| CWE-89 | 13 | 0.818 |
| CWE-327 | 8 | 0.400 |
| CWE-79 | 8 | 0.400 |
| CWE-22 | 6 | 0.667 |
| CWE-78 | 4 | 0.857 |
| CWE-90 | 3 | 0.500 |
| CWE-501 | 2 | 0.000 |
| CWE-330 | 1 | 0.000 |

#### epoch-10-three-way-deepseek: F1 by weakness class

| CWE | support | scanner | trained | llm | merged |
|---|---|---|---|---|---|
| CWE-89 | 30 | 0.682 | 0.767 | 0.870 | 0.382 |
| CWE-327 | 23 | 0.691 | 0.000 | 0.696 | 0.606 |
| CWE-330 | 23 | 1.000 | 0.000 | 0.792 | 0.821 |
| CWE-79 | 20 | 0.444 | 0.333 | 0.923 | 0.336 |
| CWE-78 | 12 | 0.615 | 0.720 | 0.609 | 0.436 |
| CWE-22 | 11 | 0.301 | 0.000 | 0.696 | 0.275 |
| CWE-501 | 3 | 0.667 | 0.000 | 0.667 | 0.667 |
| CWE-614 | 3 | 0.667 | 0.000 | 1.000 | 0.667 |
| CWE-90 | 3 | 0.750 | 1.000 | 0.857 | 0.400 |

#### epoch-11-scanner-and-llm: F1 by weakness class

| CWE | support | scanner | llm | merged |
|---|---|---|---|---|
| CWE-89 | 30 | 0.682 | 0.806 | 0.480 |
| CWE-327 | 23 | 0.691 | 0.638 | 0.594 |
| CWE-330 | 23 | 1.000 | 0.754 | 0.754 |
| CWE-79 | 20 | 0.444 | 0.884 | 0.408 |
| CWE-78 | 12 | 0.615 | 0.828 | 0.545 |
| CWE-22 | 11 | 0.301 | 0.692 | 0.265 |
| CWE-501 | 3 | 0.667 | 0.667 | 0.667 |
| CWE-614 | 3 | 0.667 | 0.750 | 0.545 |
| CWE-90 | 3 | 0.750 | 0.750 | 0.462 |
