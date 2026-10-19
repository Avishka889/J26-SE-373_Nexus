"""The rules C4's reports are held to, as pure functions.

The same idea as `cvss_base_score`: a report records the level a rule produced,
and its validators run the rule again on the report's own inputs. A producer can
therefore only record a level by recording the evidence that yields it, and the
claim "the final level is computed, never written by a model" is enforced by the
type system rather than asserted in prose.

Every rule has an id with a version. A study table names the rule ids it was
measured under, and a rule that changes gets a new id rather than a quiet edit,
so two epochs measured under different rules are never read as one.
"""

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

from .remediation_proposal import RiskLevel

#: The three signals the proposal combines (FR4 to FR6).
Signal = Literal["semver", "changelog", "usage"]

SIGNALS: tuple[Signal, ...] = ("semver", "changelog", "usage")

#: What moved between two version numbers, as a fact rather than a vote.
#:
#: `beyond-patch` is a change past the third position (Maven's `2.13.4.2`),
#: `qualifier` a change in the part after the numbers alone (`2.0.0-RC1` to
#: `2.0.0`), `non-semver` a number either side of which is not dotted digits at
#: all, and `unparseable` one the ecosystem's own ordering cannot read.
VersionChange = Literal[
    "major",
    "minor",
    "patch",
    "prerelease",
    "build-only",
    "beyond-patch",
    "qualifier",
    "downgrade",
    "non-semver",
    "unparseable",
]

#: What a verified sentence in the release notes says happened.
ClaimKind = Literal[
    "breaking",
    "removal",
    "behavioural",
    "deprecation",
    "security",
    "fix",
    "feature",
    "other",
]

#: What happened to one symbol, from an API diff or from a verified claim.
#: `breaking-behaviour` is a claim that says breaking without saying how;
#: `touched` is a symbol a fix or feature names without changing its surface.
ChangeKind = Literal[
    "removed",
    "signature-changed",
    "renamed",
    "breaking-behaviour",
    "behaviour-changed",
    "deprecated",
    "added",
    "touched",
]

DeployStrategy = Literal["automatic", "approval", "approval-with-rollback"]

#: What monitoring can say about a running release. `cold-start` is a free host
#: waking from sleep, which is slow and then fine, and is not an outage;
#: `classify_window` below tells it apart from `degraded`.
HealthState = Literal["healthy", "degraded", "down", "cold-start", "unknown"]

SEMVER_RULE = "semver-rule/1"
CHANGELOG_RULE = "changelog-rule/1"
USAGE_RULE = "usage-rule/1"
ARBITRATION_RULE = "safety-first-max/1"
STRATEGY_RULE = "risk-strategy/1"
HEALTH_RULE = "health-rule/1"

_ORDER: dict[RiskLevel, int] = {"low": 0, "medium": 1, "high": 2}

#: FR4, literally. A change the three positions do not name is mapped to patch
#: and says so through its own name; a number that cannot be ordered abstains
#: rather than being guessed at, and a downgrade is not an update at all.
_SEMVER: dict[VersionChange, RiskLevel | None] = {
    "major": "high",
    "minor": "medium",
    "patch": "low",
    "prerelease": "low",
    "build-only": "low",
    "beyond-patch": "low",
    "qualifier": "low",
    "downgrade": None,
    "non-semver": None,
    "unparseable": None,
}

_CLAIM: dict[ClaimKind, RiskLevel] = {
    "breaking": "high",
    "removal": "high",
    "behavioural": "medium",
    "deprecation": "medium",
    "security": "low",
    "fix": "low",
    "feature": "low",
    "other": "low",
}

_CHANGE: dict[ChangeKind, RiskLevel] = {
    "removed": "high",
    "signature-changed": "high",
    "renamed": "high",
    "breaking-behaviour": "high",
    "behaviour-changed": "medium",
    "deprecated": "medium",
    "added": "low",
    "touched": "low",
}

_STRATEGY: dict[RiskLevel, DeployStrategy] = {
    "low": "automatic",
    "medium": "approval",
    "high": "approval-with-rollback",
}


def most_cautious(levels: Iterable[RiskLevel]) -> RiskLevel | None:
    """The highest of some levels, or None when there are none."""
    found = list(levels)
    return max(found, key=_ORDER.__getitem__) if found else None


def semver_level(change: VersionChange) -> RiskLevel | None:
    """Signal one and the baseline: the version number alone (`semver-rule/1`)."""
    return _SEMVER[change]


def changelog_level(
    verified: Iterable[ClaimKind], *, notes_found: bool, refused: int
) -> RiskLevel | None:
    """Signal two: the level the verified claims support (`changelog-rule/1`).

    Only verified claims count, so a quote that is not in the notes can neither
    raise nor lower the level. Notes that were read and hold nothing the rule
    names are evidence of a quiet release, which is low. No notes at all, or
    notes whose every claim was refused, is no evidence, and the signal abstains
    rather than calling that low.
    """
    kinds = list(verified)
    if kinds:
        return most_cautious(_CLAIM[kind] for kind in kinds)
    if not notes_found or refused > 0:
        return None
    return "low"


def usage_level(
    referenced: Iterable[ChangeKind], *, changed_symbols_known: bool
) -> RiskLevel | None:
    """Signal three: what the project's own use of the changes implies (`usage-rule/1`).

    `referenced` is the kind of every changed symbol the project's code was
    found to use. Nothing changed in use is low project specific impact,
    recorded as such; with no changed symbols known at all there is nothing to
    look for, and the signal abstains rather than reporting that it found
    nothing.
    """
    if not changed_symbols_known:
        return None
    return most_cautious(_CHANGE[kind] for kind in referenced) or "low"


def safety_first(
    votes: Mapping[Signal, RiskLevel | None],
) -> tuple[RiskLevel, tuple[Signal, ...]]:
    """The final level and the signals that decided it (`safety-first-max/1`).

    FR6: the more cautious classification whenever the signals disagree, which
    over three signals is the highest vote cast. An abstention is not a vote.
    With no votes at all nothing supports a lower level, so the answer is high,
    decided by nobody, and the report must say so.
    """
    cast = {signal: level for signal, level in votes.items() if level is not None}
    final = most_cautious(cast.values())
    if final is None:
        return "high", ()
    return final, tuple(signal for signal in SIGNALS if cast.get(signal) == final)


def strategy_for(final: RiskLevel) -> DeployStrategy:
    """FR17: how an update at this level may ship (`risk-strategy/1`).

    FR18's mandatory manual review and FR19's prepared rollback are both
    exactly the high case, which the report derives from this rather than
    storing separately.
    """
    return _STRATEGY[final]


def classify_window(
    rounds: Sequence[tuple[bool, float | None, str | None]],
    *,
    expected: str,
    min_samples: int = 3,
    degraded_p95_ms: float = 2000,
    cold_start_first_ms: float = 90000,
    idle_seconds: float | None = None,
    cold_start_idle_seconds: float = 900,
) -> tuple[HealthState, str]:
    """What a monitoring window saw, as one state and the evidence for it (`health-rule/1`).

    Each round is (every probe answered as it must, the slowest answer in ms,
    the candidate hash `/release.json` named), oldest first. In order:

    - fewer rounds than `min_samples` is `unknown`: too little to say anything;
    - the newest fingerprint not the verified one is `down`: the release a
      person approved is not what is served, however well the other one answers;
    - the newest `min_samples` rounds all failing is `down`;
    - a host idle for at least `cold_start_idle_seconds` whose first round
      failed or was slow, within `cold_start_first_ms`, and which answered every
      round after it within `degraded_p95_ms`, is `cold-start`: a free host
      waking, not an outage. A host still slow after its first round is not
      waking; it is slow;
    - any failed round, or a p95 over `degraded_p95_ms`, is `degraded`;
    - otherwise `healthy`.
    """
    if len(rounds) < min_samples:
        return (
            "unknown",
            f"{len(rounds)} round(s) of probes, fewer than the {min_samples} the rule needs",
        )
    fingerprints = [fingerprint for _, _, fingerprint in rounds if fingerprint]
    if fingerprints and fingerprints[-1] != expected:
        return (
            "down",
            f"it serves candidate {fingerprints[-1][:12]}, not the verified {expected[:12]}",
        )
    recent = rounds[-min_samples:]
    if not any(ok for ok, _, _ in recent):
        return "down", f"the last {min_samples} rounds of probes all failed"
    first_ok, first_ms, _ = rounds[0]
    woke = idle_seconds is not None and idle_seconds >= cold_start_idle_seconds
    slow_start = not first_ok or (first_ms is not None and first_ms > degraded_p95_ms)
    within = first_ms is None or first_ms <= cold_start_first_ms
    awake = all(ok and (ms is None or ms <= degraded_p95_ms) for ok, ms, _ in rounds[1:])
    if woke and slow_start and within and awake:
        return (
            "cold-start",
            f"idle for {idle_seconds:.0f}s, the first round was slow or failed, and every round "
            f"after it answered within {degraded_p95_ms:.0f} ms",
        )
    failed = sum(1 for ok, _, _ in rounds if not ok)
    if failed:
        return "degraded", f"{failed} of {len(rounds)} rounds had a probe fail"
    latencies = sorted(ms for ok, ms, _ in rounds if ok and ms is not None)
    p95 = latencies[max(0, math.ceil(0.95 * len(latencies)) - 1)] if latencies else None
    if p95 is not None and p95 > degraded_p95_ms:
        return "degraded", f"p95 {p95:.0f} ms, over the {degraded_p95_ms:.0f} ms threshold"
    return (
        "healthy",
        f"{len(rounds)} rounds answered" + (f", p95 {p95:.0f} ms" if p95 is not None else ""),
    )


# ------------------------------------------------------------------ candidates


def candidate_hash(tree: Mapping[str, str], *, fingerprint: str) -> str:
    """One hash over every file the candidate is built from, except the one that carries it.

    A rule rather than a detail of the pipeline, because three places hold a
    candidate to it: pipeline generation fixes it, staging checks the files it
    builds hash to it, and a release checks the tree it commits does too, so
    what ships is exactly what staging verified.
    """
    digest = hashlib.sha256()
    for path in sorted(tree):
        if path == fingerprint:
            continue
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(tree[path].encode("utf-8")).hexdigest().encode())
        digest.update(b"\n")
    return digest.hexdigest()


def fingerprint_file(layer: Mapping[str, str]) -> str | None:
    """The fingerprint's path in a deployment layer: the one `public/release.json` it carries."""
    found = [path for path in layer if path.endswith("public/release.json")]
    return found[0] if len(found) == 1 else None
