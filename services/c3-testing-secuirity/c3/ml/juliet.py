"""Juliet Java as method level training examples, split so the model cannot cheat.

Juliet is 46,793 generated Java files carrying 113 weakness classes, and it is
public domain, which is why it can train a model that ships in this repository.
It is also a dataset with a famous trap, and most of this module is about the
trap rather than about the parsing.

**The trap.** Every file contains a `bad()` method and one or more `good...()`
methods that differ from it by a line or two, because they were generated from
the same template with one substitution. A random split puts a `bad` in the
training set and its near identical `good` in the test set, and the resulting
model scores beautifully by memorising the template rather than by learning
anything about the weakness. The same functional variant, say
`console_readLine_executeUpdate`, is then re-emitted under seventy control flow
wrappers, so even splitting by file leaves near duplicates on both sides.

**What is done about it.** The split key is the family: the weakness class plus
the functional variant, everything before the flow variant number. Every flow
variant of `CWE89_SQL_Injection__console_readLine_executeUpdate` lands in the
same split, and so do the multi file variants that share state across `68a` and
`68b`. The good and bad halves of a file are in the same split by construction,
because they are in the same file.

**And the leakage is measured rather than asserted.** `split` can also produce
the naive per file split, so the study can train both ways and report the gap.
A number that is ten points higher under the naive split is the leakage,
quantified, on the dataset whose documentation only warns about it.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Split = Literal["train", "validation", "test"]

#: Where the unpacked archive keeps its test cases.
TESTCASES = Path("Java/src/testcases")

#: `CWE89_SQL_Injection__console_readLine_executeUpdate_06.java` in parts: the
#: weakness class, the functional variant, the flow variant, and the multi file
#: suffix when there is one.
_NAME = re.compile(
    r"^(?P<cwe>CWE(?P<number>\d+)_[A-Za-z0-9_]+?)__(?P<variant>.+?)_(?P<flow>\d+)"
    r"(?:(?P<part>[a-z])|_(?P<role>base|bad|good[A-Za-z0-9]*))?$"
)

#: Methods that carry a weakness, and methods that do not. `good()` itself is
#: excluded by `_DISPATCH`: it only calls the others and contains no flow, so
#: labelling it safe would teach the model that a method calling two methods is
#: safe, which is true of nothing.
_BAD = re.compile(r"^bad(Sink|Source|_.*)?\d*$")
_GOOD = re.compile(r"^good[A-Za-z0-9_]*$")
_DISPATCH = frozenset({"good", "main", "toString"})

#: Variant 81 puts the flow in an abstract method and splits one test case
#: across four files, so the label is on the filename rather than on the method
#: name: `..._81_bad.java` implements `action` badly and `..._81_goodG2B.java`
#: implements it well. 2,739 files, six percent of the corpus, and dropping
#: them would silently drop the whole abstract method flow variant.
_ROLE_IS_BAD = frozenset({"bad"})
#: The abstract parent declares `action` and implements nothing. There is no
#: flow in it to label.
_ROLE_HAS_NO_FLOW = frozenset({"base"})
#: What variant 81 calls the method carrying the flow.
_ROLE_METHODS = frozenset({"action", "processMessage", "runTest"})

#: A method too short to contain a flow is template scaffolding, and one too
#: long is mostly the try/finally boilerplate Juliet wraps everything in. Both
#: bounds are in lines and both are deliberately loose.
MIN_LINES = 3
MAX_LINES = 400


@dataclass(frozen=True)
class Example:
    """One method, its label, and where it came from.

    `family` is the split key and is carried on every example, so a split can
    be checked after the fact rather than trusted.
    """

    cwe: str
    #: True when this method contains the weakness the file is named for.
    vulnerable: bool
    method: str
    code: str
    family: str
    path: str
    flow_variant: str

    @property
    def label(self) -> int:
        return 1 if self.vulnerable else 0


def family_of(path: str | Path) -> str:
    """The split key: weakness class plus functional variant, no flow variant.

    `CWE89_SQL_Injection__console_readLine_executeUpdate_06` and its sixty nine
    siblings all answer `CWE89_SQL_Injection__console_readLine_executeUpdate`,
    so they cannot be split apart. A name that does not parse answers with the
    stem, which keeps it whole rather than scattering it.
    """
    stem = Path(path).stem
    match = _NAME.match(stem)
    return f"{match['cwe']}__{match['variant']}" if match else stem


def cwe_of(path: str | Path) -> str:
    """`CWE-89` from the directory Juliet filed it under."""
    match = _NAME.match(Path(path).stem)
    return f"CWE-{match['number']}" if match else ""


def flow_variant_of(path: str | Path) -> str:
    match = _NAME.match(Path(path).stem)
    if not match:
        return ""
    tail = match["part"] or (f"_{match['role']}" if match["role"] else "")
    return f"{match['flow']}{tail}"


def role_of(path: str | Path) -> str:
    """`bad`, `good...` or `base` for the variants that label by filename."""
    match = _NAME.match(Path(path).stem)
    return match["role"] or "" if match else ""


def methods_in(source: str) -> list[tuple[str, str]]:
    """Every method in a Java file, as its name and its whole text.

    Brace matching rather than a parser, because Juliet is generated from
    templates and its shapes are regular. String literals, character literals
    and both comment forms are skipped, since a brace inside any of them would
    otherwise end a method early and hand the model a truncated example.
    """
    found: list[tuple[str, str]] = []
    for match in re.finditer(
        r"(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?"
        r"[\w<>\[\],.\s]+?\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s.]+)?\{",
        source,
    ):
        name = match.group(1)
        end = _closing_brace(source, match.end() - 1)
        if end is None:
            continue
        found.append((name, source[match.start() : end + 1]))
    return found


def _closing_brace(source: str, opening: int) -> int | None:
    """Where the block opened at `opening` ends, ignoring braces in literals."""
    depth = 0
    index = opening
    length = len(source)
    while index < length:
        character = source[index]
        if character == "/" and index + 1 < length:
            following = source[index + 1]
            if following == "/":
                index = source.find("\n", index)
                if index == -1:
                    return None
                continue
            if following == "*":
                index = source.find("*/", index)
                if index == -1:
                    return None
                index += 2
                continue
        elif character in "\"'":
            index = _end_of_literal(source, index)
            if index is None:
                return None
            continue
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _end_of_literal(source: str, opening: int) -> int | None:
    quote = source[opening]
    index = opening + 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == quote:
            return index + 1
        index += 1
    return None


def examples_in(path: str | Path, source: str) -> list[Example]:
    """The labelled methods of one Juliet file.

    A method is vulnerable when Juliet named it `bad`, safe when it named it
    `good`, and skipped when it is neither: the dispatcher, the constructor and
    the servlet plumbing carry no flow and would teach nothing.
    """
    cwe = cwe_of(path)
    if not cwe:
        return []
    role = role_of(path)
    if role in _ROLE_HAS_NO_FLOW:
        return []
    family = family_of(path)
    flow = flow_variant_of(path)
    found: list[Example] = []
    for name, code in methods_in(source):
        if name in _DISPATCH:
            continue
        if role:
            # The filename carries the label here, so only the method that
            # implements the flow is an example and everything else in the
            # file is plumbing.
            if name not in _ROLE_METHODS:
                continue
            vulnerable = role in _ROLE_IS_BAD
        elif _BAD.match(name):
            vulnerable = True
        elif _GOOD.match(name):
            vulnerable = False
        else:
            continue
        lines = code.count("\n") + 1
        if lines < MIN_LINES or lines > MAX_LINES:
            continue
        found.append(
            Example(
                cwe=cwe,
                vulnerable=vulnerable,
                method=name,
                code=code,
                family=family,
                path=str(path),
                flow_variant=flow,
            )
        )
    return found


#: A class needs at least this many families before a split can give it train,
#: validation and test rows. Below it, the class trains and is honestly absent
#: from the per class scores rather than being reported on two examples.
MIN_FAMILIES = 6


def split_position(key: str, *, seed: str = "c3") -> float:
    """A stable number in [0, 1) for a key, from its hash.

    Deterministic and order independent: the same key answers the same on any
    machine, without an assignment file to keep in step with the data. The seed
    is part of the epoch, so changing it opens a new one.
    """
    digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return int(digest[:8], 16) / 0x100000000


def assign_splits(
    examples: list[Example],
    *,
    by: Literal["family", "file"] = "family",
    seed: str = "c3",
    ratios: tuple[float, float] = (0.8, 0.9),
) -> dict[str, Split]:
    """Which split each key belongs to, stratified within its weakness class.

    Stratified because the study reports per class precision and recall, and a
    plain hash over all keys leaves most of Juliet's classes with no test rows
    at all: the small ones have one or two families, and a hash sends both to
    the same place. Ranking families inside their own class instead gives every
    class with enough of them a share of all three splits.

    A class with fewer than `MIN_FAMILIES` cannot be divided three ways without
    reporting a score on a handful of examples, so all of it trains and the
    manifest says which classes those were. That is a smaller dataset honestly
    described, rather than a per class table with rows nobody should read.

    `by="file"` is the naive split, kept so the leakage can be measured: train
    both ways and the gap between the two scores is the number Juliet's
    documentation warns about without quantifying.
    """
    keys_by_cwe: dict[str, set[str]] = {}
    for example in examples:
        key = example.family if by == "family" else example.path
        keys_by_cwe.setdefault(example.cwe, set()).add(key)

    assigned: dict[str, Split] = {}
    for keys in keys_by_cwe.values():
        ordered = sorted(keys, key=lambda key: (split_position(key, seed=seed), key))
        if len(ordered) < MIN_FAMILIES:
            assigned.update(dict.fromkeys(ordered, "train"))
            continue
        first = max(1, round(len(ordered) * ratios[0]))
        second = max(first + 1, round(len(ordered) * ratios[1]))
        second = min(second, len(ordered) - 1)
        for index, key in enumerate(ordered):
            if index < first:
                assigned[key] = "train"
            elif index < second:
                assigned[key] = "validation"
            else:
                assigned[key] = "test"
    return assigned


def evaluable(examples: list[Example], *, by: Literal["family", "file"] = "family") -> set[str]:
    """The classes with enough families to carry a per class score."""
    keys: dict[str, set[str]] = {}
    for example in examples:
        keys.setdefault(example.cwe, set()).add(example.family if by == "family" else example.path)
    return {cwe for cwe, found in keys.items() if len(found) >= MIN_FAMILIES}


def read_corpus(root: str | Path) -> list[Example]:
    """Every labelled method under an unpacked Juliet checkout.

    `root` is the directory the archive unpacks to; the test cases are found
    under it, so either the archive root or the test case directory itself
    works and a reader does not have to remember which.
    """
    base = Path(root)
    cases = base / TESTCASES if (base / TESTCASES).is_dir() else base
    found: list[Example] = []
    for path in sorted(cases.rglob("*.java")):
        found.extend(examples_in(path.relative_to(cases), path.read_text(errors="replace")))
    return found
