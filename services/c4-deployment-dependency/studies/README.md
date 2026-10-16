# The dependency update study

Everything a number in the write up was computed from, kept so the number can be
recomputed and traced to the runs that produced it.

| Path | Holds |
|---|---|
| `clients/` | The projects updates are applied to, frozen, with where each came from (`clients/README.md`) |
| `pins/` | The lockfiles the npm cases start from: each client's tree as the loader resolved it, and each case records the hash of the one it used |
| `cases/seed/` | The seed set: one `LabelledCase` per file, storing what was observed, never a label |
| `epochs/` | One study record per epoch: every arm's scores, per case predictions, the corpus hash, the rubric and the commit |

The level of a case is derived when it is read, by `outcome-rubric/1`
(`c4/eval/rubric.py`), and which side of the split it is on is a hash of its
update's key (`c4/eval/split.py`). Neither is stored, so neither can drift.

## Rebuilding and rerunning

The seed set is rebuilt by its loaders, locally and without a model:

```
git clone --depth 1 --filter=blob:none --sparse https://github.com/chains-project/bump ~/.cache/sdlc-c4/bump
git -C ~/.cache/sdlc-c4/bump sparse-checkout set data/benchmark
uv run python -m c4.eval.seed --bump ~/.cache/sdlc-c4/bump
```

A case already in `cases/seed/` is kept rather than observed again, so deleting
a file is how one case is re-observed. Observing runs containers through the
local Docker daemon, from images pinned by digest, and downloads packages from
the public registries.

An epoch is run on the dev split and its table printed:

```
uv run python -m c4.eval --cases studies/cases/seed --epoch "Epoch 1, seed set" --commit SHA --out studies/epochs
uv run python -m c4.eval --tables studies/epochs
```

The held out cases are read once, for the final evaluation, and the study
refuses to read them without `--split held-out --final`.
