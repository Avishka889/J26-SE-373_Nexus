# Training the detection model on Colab

The GPU hours happen outside this repository, so this is the whole handover:
what to upload, what to run, and what to bring back. Nothing here needs the
service package installed, because the only environment `train.py` ever runs in
is a fresh runtime.

Everything the numbers are computed from comes back as data. **The scores are
not produced on Colab.** A notebook's accuracy line cannot be reviewed, cannot
be recomputed when the definition of a match changes, and disappears when the
runtime is reclaimed, so Colab writes predictions and this repository writes
numbers.

## What to upload

Two files, 4.9 MB and 9 KB:

| File | Where it is | What it is |
|---|---|---|
| `juliet-prepared.tar.gz` | `~/datasets/juliet-prepared.tar.gz` | the three splits and the manifest, 147,575 labelled methods |
| `train.py` | `services/c3-testing-security/c3/ml/train.py` | the training script |

If the tarball is missing, rebuild it:

```
uv run python -m c3.ml.export --juliet ~/datasets/juliet-java-1.3 \
    --out ~/datasets/juliet-prepared --archive ~/datasets/juliet-java-1.3.zip
tar czf ~/datasets/juliet-prepared.tar.gz -C ~/datasets/juliet-prepared .
```

## What to run

**Runtime type: T4 GPU.** It will run on CPU and will take most of a day.

```python
# 1. Confirm the GPU is there. If this prints nothing, change the runtime type.
!nvidia-smi
```

```python
# 2. Upload the two files (or drag them into the file browser).
from google.colab import files

files.upload()
```

```python
# 3. Unpack and install. Torch is already on Colab; transformers usually is not.
!mkdir -p /content/juliet && tar xzf juliet-prepared.tar.gz -C /content/juliet
!pip install -q transformers
!ls /content/juliet
```

```python
# 4. Smoke run first. Two hundred rows, one epoch, about a minute. This is the
#    first time the torch path has ever executed, so let it fail here rather
#    than forty minutes into the real run.
!python train.py --data /content/juliet --out /content/smoke --limit 200 --epochs 1
```

The smoke run should print `training on cuda`, three split sizes, one epoch
line, a test accuracy, and the list of files it wrote. **The accuracy from a
two hundred row run means nothing**; what is being checked is that it runs.

```python
# 5. The real run. Roughly 10 to 20 minutes per epoch on a T4, so half an hour
#    to an hour in total. It prints a progress line every 200 steps.
!python train.py --data /content/juliet --out /content/model --epochs 3
```

If the session looks likely to be reclaimed, `--epochs 2` is a perfectly
reportable run: the epoch count is recorded in `run.json` and the number is
honest either way.

## What to bring back

```python
# The small set: the numbers. A few megabytes.
!tar czf results.tar.gz -C /content/model labels.json run.json test-predictions.jsonl
from google.colab import files
files.download('results.tar.gz')
```

That is enough for every number in the study. `test-predictions.jsonl` has one
row per test example with its true and predicted label and class, its family,
and the model's own probability.

```python
# The weights, only if the arm should also run locally. About 500 MB, so Drive
# rather than a browser download.
from google.colab import drive
drive.mount('/content/drive')
!tar czf /content/drive/MyDrive/c3-model.tar.gz -C /content/model .
```

The weights are needed for one thing: running the trained arm as a live
detector, which is what the definition of done's security stage shows. The
per class table needs only the small set.

### Where the weights go

**`~/models/c3-juliet/`**, outside the repository. Not inside it: half a
gigabyte in the working tree slows every search down, and a directory that is
gitignored rather than tracked is exactly what `git clean -xdf` deletes without
asking. Three hours of GPU time should not be one routine command away from
gone.

```
mkdir -p ~/models/c3-juliet
tar xzf /mnt/c/Users/<you>/Downloads/c3-model.tar.gz -C ~/models/c3-juliet
ls ~/models/c3-juliet
```

Then check it before running anything over it:

```
uv run python -c "
import sys; sys.path.insert(0, 'services/c3-testing-security')
from c3.detect import TrainedArm
from c3.detect.trained import ModelProcess
arm = TrainedArm(model_dir='$HOME/models/c3-juliet')
print('offline:', arm.offline)
process = ModelProcess('$HOME/models/c3-juliet'); process.start()
print('missing:', process.failure or 'nothing')
"
```

`offline: True` and `missing: nothing` means the directory is complete and the
arm can run with the network unplugged. **`offline: False` means `config.json`
or the tokenizer did not come across**: the arm will still work by fetching
them from the hub, and it will correctly stop claiming to be offline, which is
this arm's whole argument. That claim is derived from what is in the directory
rather than asserted by the code.

## What happens when it lands

Unpack the results anywhere, then:

```
uv run python -m c3.eval.predictions --model ~/models/c3-juliet \
    --out services/c3-testing-security/studies/juliet-trained.json
```

That prints two tables and writes the study file: detection (vulnerable or not,
over all 14,094 test examples) and classification (which weakness, over the
methods that really have one). They are separate because two thirds of Juliet
is safe, so a model answering "safe" to everything scores 0.68 on the first and
nothing on the second.

If the weights came back too, put the directory somewhere and the arm runs:

```
uv run python -m c3.eval --benchmark cwe-bench --checkout ~/datasets/cwe-bench-java \
    --sources ~/datasets/cwe-bench-sources --arms trained --model ~/models/c3-juliet
```

## What is in the directory that comes back

| File | Why it matters |
|---|---|
| `test-predictions.jsonl` | every test example, its truth and its prediction. The numbers come from here |
| `run.json` | base model, epochs, batch, learning rate, seed, split rule, counts. The epoch |
| `labels.json` | which class index means which weakness. **The weights are meaningless without it** |
| `weights.pt` | the trained model, about 500 MB |
| `config.json`, tokenizer files | so the served model needs no network, which is the arm's whole claim |

## Two things that will bite

**The label file travels with the weights, always.** A model whose class index
seven means something different from the code's index seven produces confident
nonsense and nothing about it looks wrong. A test in this repository asserts the
two definitions agree; that test cannot help if the file is lost.

**Do not re-export the dataset between training and scoring.** The split is
derived from a seed, so it is reproducible, but changing the seed opens a new
epoch and the predictions would be scored against a different test set than the
one they came from.
