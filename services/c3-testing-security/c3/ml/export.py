"""Juliet as files a Colab notebook can train on, with the provenance attached.

The GPU hours happen outside this session, so what leaves here has to carry
everything a reader needs to know what was trained on. The manifest is the
point of this module: counts per split and per class, the split rule and its
seed, the classes that were too small to score and why they were kept out, the
checksum of the archive, and the date. A model whose training set cannot be
described is a model whose numbers cannot be used, and this component's rule is
that every number carries its epoch.

Deliberately plain JSONL. The notebook that reads this should be readable by
somebody who has never seen this repository, and a custom format would make the
training script depend on code that is not there.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .juliet import MIN_FAMILIES, Example, assign_splits, evaluable, read_corpus

#: What one example looks like on disk. Named here because the training script
#: reads these keys and it should be possible to check the two agree without
#: running either.
FIELDS = ("code", "label", "cwe", "method", "family", "path", "flowVariant", "split")


def as_row(example: Example, split: str) -> dict:
    return {
        "code": example.code,
        "label": example.label,
        "cwe": example.cwe,
        "method": example.method,
        "family": example.family,
        "path": example.path,
        "flowVariant": example.flow_variant,
        "split": split,
    }


def checksum(path: Path) -> str:
    """The archive's sha256, so a reader can tell which Juliet this was."""
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def export(
    root: str | Path,
    out_dir: str | Path,
    *,
    by: Literal["family", "file"] = "family",
    seed: str = "c3",
    archive: str | Path | None = None,
) -> dict:
    """Write the three splits and the manifest, and return the manifest.

    Every class trains. Only the classes with enough families to be divided
    three ways are marked evaluable, and the per class scores are reported for
    those: a precision computed over four test examples is a number that will
    be read as though it meant something.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    examples = read_corpus(root)
    assigned = assign_splits(examples, by=by, seed=seed)
    scorable = evaluable(examples, by=by)

    counts: Counter[str] = Counter()
    labels: dict[str, Counter[int]] = defaultdict(Counter)
    per_cwe: dict[str, Counter[str]] = defaultdict(Counter)
    handles = {name: (out / f"{name}.jsonl").open("w") for name in ("train", "validation", "test")}
    try:
        for example in examples:
            key = example.family if by == "family" else example.path
            split = assigned[key]
            handles[split].write(json.dumps(as_row(example, split)) + "\n")
            counts[split] += 1
            labels[split][example.label] += 1
            per_cwe[example.cwe][split] += 1
    finally:
        for handle in handles.values():
            handle.close()

    manifest = {
        "dataset": "Juliet Test Suite for Java v1.3 (NIST SARD)",
        "licence": "CC0 1.0, public domain",
        "generatedAt": datetime.now(UTC).isoformat(),
        "archiveSha256": checksum(Path(archive)) if archive else "",
        "splitRule": {
            "by": by,
            "seed": seed,
            "stratified": "within each weakness class",
            "minFamiliesToScore": MIN_FAMILIES,
            "why": (
                "Juliet pairs a bad method with a near identical good one in the same "
                "file and re-emits each functional variant under seventy control flow "
                "wrappers. Splitting by family keeps every variant of one source and "
                "sink pair on one side, so a score cannot be earned by memorising a "
                "template. Splitting by file is the naive rule and is kept so the "
                "leakage can be measured rather than asserted."
            ),
        },
        "counts": dict(counts),
        "vulnerableFraction": {
            split: round(found[1] / max(1, sum(found.values())), 4)
            for split, found in labels.items()
        },
        "classes": {
            cwe: dict(found)
            for cwe, found in sorted(per_cwe.items(), key=lambda item: -sum(item[1].values()))
        },
        "evaluableClasses": sorted(scorable),
        "trainOnlyClasses": sorted(set(per_cwe) - scorable),
        "trainOnlyReason": (
            f"fewer than {MIN_FAMILIES} families, so a three way split would report a "
            "per class score on a handful of examples. These classes train and are "
            "absent from the per class table, which is the honest description of a "
            "dataset that does not contain enough of them."
        ),
        "fields": list(FIELDS),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--juliet", required=True, help="the unpacked archive")
    parser.add_argument("--out", required=True, help="where the jsonl and manifest go")
    parser.add_argument("--by", choices=("family", "file"), default="family")
    parser.add_argument("--seed", default="c3")
    parser.add_argument("--archive", default="", help="the zip, for its checksum")
    arguments = parser.parse_args()
    manifest = export(
        arguments.juliet,
        arguments.out,
        by=arguments.by,
        seed=arguments.seed,
        archive=arguments.archive or None,
    )
    print(json.dumps({key: manifest[key] for key in ("counts", "evaluableClasses")}, indent=2))


if __name__ == "__main__":
    main()
