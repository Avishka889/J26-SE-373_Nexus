"""The label space, decided here so that training and inference cannot disagree.

Two heads rather than one, and the reason is the data. A binary head learns
from all 147,575 examples, including the seventy one weakness classes with too
few families to be scored on their own; a class head learns only from the
vulnerable ones, over the classes the split can actually divide three ways.
Folding both into a single "safe plus N classes" head would either throw away
the small classes or report per class scores on a handful of examples, and both
of those are worse than having two heads.

The mapping lives in a file the trained weights travel with. A model whose
class index 7 means something different from the code's class index 7 is a
model that produces confident nonsense, and nothing about it would look wrong.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

#: What a vulnerable method is called when its class is not one the split can
#: score. It still trains the binary head and it still teaches the class head
#: that not every weakness is one of the named ones.
OTHER = "other"


@dataclass(frozen=True)
class LabelSpace:
    """Which class index means which weakness, in both directions."""

    classes: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.classes)

    def index_of(self, cwe: str) -> int:
        try:
            return self.classes.index(cwe)
        except ValueError:
            return self.classes.index(OTHER)

    def cwe_at(self, index: int) -> str:
        return self.classes[index] if 0 <= index < self.size else OTHER

    def as_dict(self) -> dict:
        return {"classes": list(self.classes), "other": OTHER}

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.as_dict(), indent=2) + "\n")

    @classmethod
    def read(cls, path: str | Path) -> "LabelSpace":
        data = json.loads(Path(path).read_text())
        return cls(classes=tuple(data["classes"]))

    @classmethod
    def over(cls, evaluable: Iterable[str]) -> "LabelSpace":
        """The scorable classes in a fixed order, plus the catch all.

        Sorted by their number rather than as strings, so the file reads in an
        order a human expects and two runs over the same class set produce the
        same indices.
        """
        ordered = sorted({cwe for cwe in evaluable if cwe != OTHER}, key=_number)
        return cls(classes=(*ordered, OTHER))


def _number(cwe: str) -> int:
    digits = "".join(character for character in cwe if character.isdigit())
    return int(digits) if digits else 0
