"""Fine tune GraphCodeBERT on the exported splits. Runs on Colab, not here.

This machine has 5.8 GB of memory and a 2 GB laptop GPU, so the training runs
elsewhere and this file is what gets uploaded. It is deliberately a plain
PyTorch loop rather than `Trainer`: the loop is thirty lines, it can be read by
somebody debugging a Colab session at midnight, and it does not break when a
keyword argument is renamed in a minor release.

It imports nothing from this repository. A training script that needs the
service package installed is a training script that cannot be dropped into a
fresh runtime, which is the only environment it will ever run in.

What it writes back is what this repository needs: the weights, the label file
the weights are meaningless without, and a predictions file over the test split
with one row per example. The scores are computed from that file by
`c3.eval.scoring`, in the repository, under test, rather than by a print
statement in a cell that no longer exists.

    !pip install -q transformers torch
    !python train.py --data /content/juliet --out /content/model --epochs 3
"""

import argparse
import json
import random
import time
from pathlib import Path

#: Microsoft's code model pre trained on code plus data flow, which is the
#: reason to prefer it here over a plain text encoder: the weaknesses in this
#: dataset are dataflow from a source to a sink.
BASE_MODEL = "microsoft/graphcodebert-base"

#: Its position embedding limit is 512, and a Juliet method that overflows it
#: is mostly try/finally boilerplate at the end.
MAX_TOKENS = 512
OTHER = "other"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def label_space(manifest: dict) -> list[str]:
    """The class head's vocabulary, from the manifest the export wrote."""
    ordered = sorted(
        manifest["evaluableClasses"],
        key=lambda cwe: int("".join(c for c in cwe if c.isdigit()) or 0),
    )
    return [*ordered, OTHER]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="where export wrote the jsonl")
    parser.add_argument("--out", required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--limit", type=int, default=0, help="rows per split, for a smoke run")
    arguments = parser.parse_args()

    import torch
    from torch import nn
    from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

    random.seed(arguments.seed)
    torch.manual_seed(arguments.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"training on {device}")

    data = Path(arguments.data)
    manifest = json.loads((data / "manifest.json").read_text())
    classes = label_space(manifest)
    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "labels.json").write_text(json.dumps({"classes": classes, "other": OTHER}, indent=2))

    splits = {name: read_jsonl(data / f"{name}.jsonl") for name in ("train", "validation", "test")}
    if arguments.limit:
        splits = {name: rows[: arguments.limit] for name, rows in splits.items()}
    for name, rows in splits.items():
        print(f"{name}: {len(rows)} examples")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    encoder = AutoModel.from_pretrained(BASE_MODEL).to(device)
    # Saved beside the weights so the served model needs no network. The
    # trained arm's headline claim is that it runs offline, and an artefact
    # that downloads its own tokenizer on first use does not.
    tokenizer.save_pretrained(out)
    encoder.config.save_pretrained(out)

    class TwoHeads(nn.Module):
        """One encoder, two heads: is it vulnerable, and if so which class.

        The class head is trained only on the vulnerable rows. Teaching it a
        class for a safe method would be teaching it that safe methods have
        weakness classes, which is the confusion the binary head exists to
        avoid.
        """

        def __init__(self) -> None:
            super().__init__()
            self.encoder = encoder
            width = encoder.config.hidden_size
            self.dropout = nn.Dropout(0.1)
            self.binary = nn.Linear(width, 2)
            self.cwe = nn.Linear(width, len(classes))

        def forward(self, **encoded):
            pooled = self.dropout(self.encoder(**encoded).last_hidden_state[:, 0])
            return self.binary(pooled), self.cwe(pooled)

    model = TwoHeads().to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=arguments.lr)
    loss_of = nn.CrossEntropyLoss()
    index_of = {cwe: position for position, cwe in enumerate(classes)}

    per_epoch = max(1, len(splits["train"]) // arguments.batch)
    steps = per_epoch * arguments.epochs
    schedule = get_linear_schedule_with_warmup(optimiser, int(steps * 0.06), steps)
    # Half precision on a GPU, roughly twice as fast on a T4, which is the
    # difference between finishing inside a free session and not. Off on CPU,
    # where it is slower rather than faster.
    amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda") if amp else None

    def batches(rows: list[dict], shuffle: bool):
        order = list(range(len(rows)))
        if shuffle:
            random.shuffle(order)
        for start in range(0, len(order), arguments.batch):
            chosen = [rows[index] for index in order[start : start + arguments.batch]]
            encoded = tokenizer(
                [row["code"] for row in chosen],
                truncation=True,
                padding=True,
                max_length=MAX_TOKENS,
                return_tensors="pt",
            ).to(device)
            labels = torch.tensor([row["label"] for row in chosen], device=device)
            cwes = torch.tensor(
                [index_of.get(row["cwe"], index_of[OTHER]) for row in chosen], device=device
            )
            yield chosen, encoded, labels, cwes

    def macro_f1(written: list[dict]) -> float:
        """The class head's score, over the rows that really are vulnerable.

        Written out here rather than imported because this script runs in a
        fresh runtime with nothing of this repository in it. It exists for one
        reason: the binary head saturates in the first epoch, so selecting a
        checkpoint on accuracy alone is selecting blind to the head that still
        has room to improve.
        """
        counts: dict[str, list[int]] = {}
        for row in written:
            if row["trueLabel"] == 1:
                counts.setdefault(row["trueCwe"], [0, 0, 0])
            if row["trueLabel"] == 1 and row["predictedLabel"] == 1:
                if row["predictedCwe"] == row["trueCwe"]:
                    counts[row["trueCwe"]][0] += 1
                else:
                    counts[row["trueCwe"]][2] += 1
                    counts.setdefault(row["predictedCwe"], [0, 0, 0])[1] += 1
            elif row["trueLabel"] == 1:
                counts[row["trueCwe"]][2] += 1
        scores = []
        for hits, wrong, missed in counts.values():
            if hits + missed == 0:
                continue
            precision = hits / (hits + wrong) if hits + wrong else 0.0
            recall = hits / (hits + missed)
            total = precision + recall
            scores.append(2 * precision * recall / total if total else 0.0)
        return sum(scores) / len(scores) if scores else 0.0

    def evaluate(rows: list[dict]) -> tuple[float, list[dict]]:
        model.eval()
        correct = 0
        written: list[dict] = []
        with torch.no_grad():
            for chosen, encoded, labels, _ in batches(rows, shuffle=False):
                binary, cwe = model(**encoded)
                predicted = binary.argmax(dim=1)
                classified = cwe.argmax(dim=1)
                confidence = torch.softmax(binary, dim=1)[:, 1]
                correct += int((predicted == labels).sum())
                for position, row in enumerate(chosen):
                    written.append(
                        {
                            "path": row["path"],
                            "method": row["method"],
                            "family": row["family"],
                            "trueLabel": row["label"],
                            "trueCwe": row["cwe"],
                            "predictedLabel": int(predicted[position]),
                            "predictedCwe": classes[int(classified[position])],
                            "score": float(confidence[position]),
                        }
                    )
        return correct / max(1, len(rows)), written

    best = -1.0
    best_epoch = 0
    started = time.monotonic()
    for epoch in range(1, arguments.epochs + 1):
        model.train()
        running = 0.0
        seen = 0
        for _, encoded, labels, cwes in batches(splits["train"], shuffle=True):
            optimiser.zero_grad()
            with torch.autocast("cuda", dtype=torch.float16, enabled=amp):
                binary, cwe = model(**encoded)
                loss = loss_of(binary, labels)
                vulnerable = labels == 1
                if bool(vulnerable.any()):
                    loss = loss + loss_of(cwe[vulnerable], cwes[vulnerable])
            if scaler is not None:
                scaler.scale(loss).backward()
                scaler.step(optimiser)
                scaler.update()
            else:
                loss.backward()
                optimiser.step()
            schedule.step()
            running += float(loss.detach())
            seen += 1
            if seen % 200 == 0:
                # Progress, because a silent hour is indistinguishable from a
                # hung one and this runs on a session that can be reclaimed.
                # The elapsed time is on the line on purpose: this runs on a
                # session that can be reclaimed, and the only way to decide
                # early whether three epochs will fit is to watch the rate.
                done = (epoch - 1) * per_epoch + seen
                rate = done / max(0.001, time.monotonic() - started)
                left = (steps - done) / rate / 60
                print(
                    f"  epoch {epoch} step {seen}/{per_epoch}  loss {running / seen:.4f}"
                    f"  {rate:.1f} steps/s  about {left:.0f} min left",
                    flush=True,
                )
        accuracy, written = evaluate(splits["validation"])
        classes_f1 = macro_f1(written)
        # Both heads, because the binary one saturates almost immediately and
        # the class one keeps improving for epochs afterwards. Selecting on
        # accuracy alone threw away two hours of training on the first real
        # run: epochs 2 and 3 lowered the loss by a third and were discarded
        # because their accuracy was fractionally lower.
        score = (accuracy + classes_f1) / 2
        print(
            f"epoch {epoch}: loss {running / max(1, seen):.4f}  "
            f"validation accuracy {accuracy:.4f}  class macro F1 {classes_f1:.4f}  "
            f"selection score {score:.4f}  "
            f"{(time.monotonic() - started) / 60:.1f} min elapsed"
        )
        # The last epoch is always kept as well, so no run ever ends with its
        # final state unrecoverable.
        torch.save(model.state_dict(), out / "weights-last.pt")
        if score > best:
            best = score
            best_epoch = epoch
            torch.save(model.state_dict(), out / "weights.pt")
            print("  kept (best so far)")

    model.load_state_dict(torch.load(out / "weights.pt", map_location=device))
    accuracy, predictions = evaluate(splits["test"])
    with (out / "test-predictions.jsonl").open("w") as handle:
        for row in predictions:
            handle.write(json.dumps(row) + "\n")
    (out / "run.json").write_text(
        json.dumps(
            {
                "baseModel": BASE_MODEL,
                "epochs": arguments.epochs,
                "batch": arguments.batch,
                "learningRate": arguments.lr,
                "seed": arguments.seed,
                "maxTokens": MAX_TOKENS,
                "splitRule": manifest["splitRule"],
                "counts": {name: len(rows) for name, rows in splits.items()},
                "selectionScore": round(best, 4),
                "bestEpoch": best_epoch,
                "testAccuracy": round(accuracy, 4),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"test accuracy {accuracy:.4f}")
    print(f"wrote everything to {out}: weights.pt, labels.json, config.json, the tokenizer,")
    print("test-predictions.jsonl and run.json. Bring that whole directory back.")
    print("the per class scores are computed from test-predictions.jsonl by c3.eval, not here")


if __name__ == "__main__":
    main()
