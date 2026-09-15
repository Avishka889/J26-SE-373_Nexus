"""Contract evaluation metrics: P/R/F1 at three grains, and honesty stamps.

Everything here is arithmetic over two contracts: the one an arm produced and
the one a person wrote by hand. Endpoint grain matches on canonical
"METHOD path" keys; path grain asks whether the right resources exist at all,
whatever the verb; schema grain compares typed field sets over the endpoints
both sides have. Nothing here talks to a model, and nothing invents a number:
a run's stamp (model id, date, code tag) is passed in by whoever ran it.
"""

from dataclasses import dataclass

from sdlc_contracts import ApiContract, ApiEndpoint

from ..contract.vocab import canonical


@dataclass(frozen=True)
class Prf:
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        found = self.true_positives + self.false_positives
        return self.true_positives / found if found else 0.0

    @property
    def recall(self) -> float:
        wanted = self.true_positives + self.false_negatives
        return self.true_positives / wanted if wanted else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0


def prf(predicted: set, truth: set) -> Prf:
    return Prf(
        true_positives=len(predicted & truth),
        false_positives=len(predicted - truth),
        false_negatives=len(truth - predicted),
    )


def _path_of(key: str) -> str:
    """ "GET /orders/{id}" -> "/orders/{id}"."""
    return key.split(" ", 1)[1]


def _schema_facts(endpoint: ApiEndpoint) -> set[tuple[str, str, str]]:
    facts: set[tuple[str, str, str]] = set()
    for side, schema in (("request", endpoint.request), ("response", endpoint.response)):
        if schema is None:
            continue
        for field in schema.fields:
            facts.add((side, field.name, field.type))
    return facts


def contract_scores(predicted: ApiContract, truth: ApiContract) -> dict[str, Prf]:
    """The three grains, keyed exactly as the report tables name them."""
    predicted_keys = {canonical(e.method, e.path): e for e in predicted.endpoints}
    truth_keys = {canonical(e.method, e.path): e for e in truth.endpoints}

    # Path grain: did the right resources appear at all, whatever the verb.
    predicted_paths = {_path_of(key) for key in predicted_keys}
    truth_paths = {_path_of(key) for key in truth_keys}

    # Schema grain: typed fields, pooled over the endpoints both sides have.
    shared = set(predicted_keys) & set(truth_keys)
    predicted_fields = {
        (key, *fact) for key in shared for fact in _schema_facts(predicted_keys[key])
    }
    truth_fields = {(key, *fact) for key in shared for fact in _schema_facts(truth_keys[key])}

    return {
        "endpoints": prf(set(predicted_keys), set(truth_keys)),
        "paths": prf(predicted_paths, truth_paths),
        "schema_fields": prf(predicted_fields, truth_fields),
    }


def repair_convergence(attempts_per_case: list[int], *, max_attempts: int) -> dict[str, float]:
    """How often the arm needed the repair loop, and how often it gave up."""
    if not attempts_per_case:
        return {"cases": 0, "first_try_rate": 0.0, "repaired_rate": 0.0, "gave_up_rate": 0.0}
    cases = len(attempts_per_case)
    return {
        "cases": cases,
        "first_try_rate": sum(1 for a in attempts_per_case if a == 1) / cases,
        "repaired_rate": sum(1 for a in attempts_per_case if 1 < a <= max_attempts) / cases,
        "gave_up_rate": sum(1 for a in attempts_per_case if a > max_attempts) / cases,
    }


@dataclass(frozen=True)
class EvalStamp:
    """Who produced a result set: never inferred, always passed in."""

    model: str
    date: str
    code_tag: str

    def as_dict(self) -> dict[str, str]:
        return {"model": self.model, "date": self.date, "code_tag": self.code_tag}
