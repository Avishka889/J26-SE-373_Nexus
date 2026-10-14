"""Loading the corpus: designs on disk, parsed through the contracts.

The corpus lives as JSON files rather than Python, because extra="forbid"
models plus stored bodies means only additive schema changes are safe after
first storage, and a file on disk makes that a diff rather than an accident.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from sdlc_contracts import ApiContract, ArchitectureGraph, SprintPlan, WireframesArtefact

CORPUS_DIR = Path(__file__).parent / "corpus"

#: Words that name another corpus item's product. None of them can appear in
#: a calculator's generated code without something having leaked across
#: designs. Deliberately short, exactly like C1's list: a guard that fires on
#: correct output is a guard people learn to switch off.
#: "checkout" is deliberately absent: every generated CI workflow contains
#: `actions/checkout@v4`, and a guard word that fires on every correct build
#: is worse than no guard word. "basket", "shopper" and "merchant" still
#: cover the commerce corpus.
FOREIGN_WORDS = (
    "payment",
    "merchant",
    "basket",
    "shopper",
    "shipment",
    "cold chain",
    "coldchain",
    "temperature",
    "wallet",
    "invoice",
    "nexuspay",
    "shopflow",
    "meditrack",
    "notifyhub",
)

CALCULATOR_STEM = "calculat"


@dataclass(frozen=True)
class CorpusDesign:
    name: str
    graph: ArchitectureGraph
    wireframes: WireframesArtefact
    sprint: SprintPlan


def design_files() -> list[Path]:
    return sorted(CORPUS_DIR.glob("*_design.json"))


def load_design(path: Path) -> CorpusDesign:
    raw = json.loads(path.read_text())
    return CorpusDesign(
        name=raw["name"],
        graph=ArchitectureGraph.model_validate(raw["graph"]),
        wireframes=WireframesArtefact.model_validate(raw["wireframes"]),
        sprint=SprintPlan.model_validate(raw["sprint"]),
    )


def load_truth(stem: str) -> ApiContract:
    return ApiContract.model_validate(json.loads((CORPUS_DIR / f"{stem}_truth.json").read_text()))


def leaked(text: str) -> list[str]:
    lowered = text.lower()
    return [word for word in FOREIGN_WORDS if word in lowered]
