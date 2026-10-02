"""The changelog signal over a votes record's cases: the live pass, which spends model calls.

    uv run --env-file .env python -m c4.eval.changelog_pass \\
        --cases studies/cases/seed --votes studies/votes/IN.json --out studies/votes/OUT.json

Two phases, in this order, so that no call is spent on a pass that cannot finish:

1. **Notes.** Each case's release notes are fetched as the product's detection
   stage fetches them: the registry names the repository, GitHub's releases are
   read first, then a changelog file, then the npm tarball's. Every answer is
   cached. If GitHub's rate limit cuts any case short, the pass stops here,
   before any model is asked, and is run again once the limit resets; the
   cache makes the second run read what the first already fetched.
2. **The signal.** `changelog.analyse` over every case at once, one call per
   case with notes, with its own rule: a rate limit that surfaces stops it and
   the rest abstain; nothing is retried here.

The record written is the input record with each case's changelog vote filled
in, what it rests on (the claims, the refusals, the model call) and the hash of
every note text the model was shown. The texts themselves are kept outside the
repository, beside the cache, because a release note is someone else's text.
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from sdlc_contracts import DependencyUpdate, DependencyUpdates

from ..agents import recorded_settings
from ..intake import maven_central, npm_registry
from ..intake.cache import Cache
from ..intake.fetch import Fetcher
from ..intake.releases import Notes, release_notes
from ..risk.changelog import analyse
from .cases import LabelledCase
from .votes import client_for, update_for

MODEL = "deepseek:deepseek-flash"


async def notes_for(update: DependencyUpdate, fetcher: Fetcher) -> Notes:
    """The notes of every release in the update's window, found the way detection finds them."""
    if update.ecosystem == "npm":
        package = await npm_registry.fetch(fetcher, update.package)
        if isinstance(package, npm_registry.NotFound):
            return Notes(unavailable=package.detail)
        return await release_notes(
            fetcher,
            ecosystem="npm",
            package=update.package,
            old=update.from_version,
            new=update.to_version,
            repository=package.repository,
            tarball=package.tarballs.get(update.to_version),
        )
    artifact = await maven_central.fetch(fetcher, update.package)
    if isinstance(artifact, npm_registry.NotFound):
        return Notes(unavailable=artifact.detail)
    return await release_notes(
        fetcher,
        ecosystem="maven",
        package=update.package,
        old=update.from_version,
        new=update.to_version,
        repository=artifact.repository,
    )


def _commit() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or "unknown"


async def run(
    cases: list[LabelledCase],
    votes: dict,
    studies: Path,
    *,
    cache: Path,
    texts_dir: Path,
    model: str = MODEL,
    reports: Path | None = None,
    log=print,
) -> tuple[dict, bool]:
    """The record with changelog votes filled in, and whether the notes phase finished.

    The signal reads an update's release notes, which belong to the dependency and
    not to the client, so an update several cases share is read and analysed once,
    and every case that shares it gets the same vote. The record names the cases
    that shared a call, so the spend is counted once per call.
    """
    updates: list[DependencyUpdate] = []
    texts: dict[str, str] = {}
    cases_of: dict[str, list[LabelledCase]] = {}
    notes_of: dict[str, Notes] = {}
    async with httpx.AsyncClient(headers={"User-Agent": "sdlc-platform-c4-study"}) as http:
        fetcher = Fetcher(http, cache=Cache(cache))
        for case in cases:
            client = client_for(case, studies)
            update = update_for(case, client.files)
            if update.id in cases_of:
                cases_of[update.id].append(case)
                log(f"  {case.case_id}: shares its update with {cases_of[update.id][0].case_id}")
                continue
            notes = await notes_for(update, fetcher)
            log(
                f"  {case.case_id}: "
                + (
                    f"{len(notes.sections)} release notes"
                    if notes.found
                    else (notes.unavailable or "no notes")
                ),
                flush=True,
            )
            if notes.unavailable.startswith("GitHub answered with its rate limit"):
                log("GitHub's rate limit was reached: stopping before any model call.")
                return votes, False
            updates.append(
                update.model_copy(
                    update={"notes": notes.refs, "notes_unavailable": notes.unavailable}
                )
            )
            texts.update(notes.texts)
            cases_of[update.id] = [case]
            notes_of[update.id] = notes

    texts_dir.mkdir(parents=True, exist_ok=True)
    for path, text in texts.items():
        target = texts_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    report = await analyse(
        DependencyUpdates(
            version=1,
            generated_at=datetime.now(UTC),
            code_version=1,
            test_version=1,
            target="study",
            updates=updates,
        ),
        texts,
        model=model,
        version=1,
    )
    if reports is not None:
        # The whole report, quotes and all, for explanations asked later of the real
        # assessment; it holds someone else's text, so it stays outside the repository.
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "changelog-report.json").write_text(report.model_dump_json(by_alias=True) + "\n")
    recorded = json.loads(json.dumps(votes))
    for analysis in report.per_update:
        sharing = cases_of[analysis.update_id]
        call = analysis.model
        vote = {
            "level": analysis.vote.level,
            "abstained": analysis.vote.abstained_reason,
            "rationale": analysis.vote.rationale,
            "windows": analysis.windows,
            "claims": [
                {
                    "id": claim.id,
                    "kind": claim.kind,
                    "symbols": claim.symbols,
                    "version": claim.version,
                    "quote": claim.quote[:300],
                }
                for claim in analysis.claims
            ],
            "refused": [
                {"reason": refused.reason, "quote": refused.quote[:200]}
                for refused in analysis.refused
            ],
            "model": (
                {
                    "outcome": call.outcome,
                    "requests": call.requests,
                    "promptTokens": call.prompt_tokens,
                    "completionTokens": call.completion_tokens,
                    "durationSeconds": call.duration_seconds,
                    "statedLevel": call.stated_level,
                    "error": call.error,
                }
                if call is not None
                else None
            ),
            "notes": [
                {
                    "source": ref.source,
                    "url": ref.url,
                    "version": ref.version,
                    "sha256": ref.sha256,
                    "chars": ref.chars,
                    "truncated": ref.truncated,
                }
                for ref in notes_of[analysis.update_id].refs
            ],
        }
        for index, case in enumerate(sharing):
            recorded[case.case_id]["changelog"] = (
                vote if index == 0 else {**vote, "sharedWith": sharing[0].case_id}
            )
            recorded[case.case_id]["changelogRun"] = True
        log(
            f"  {sharing[0].case_id}: changelog {analysis.vote.level} "
            f"({len(analysis.claims)} verified, {len(analysis.refused)} refused"
            + (f", {call.prompt_tokens} in / {call.completion_tokens} out" if call else "")
            + (f"; shared by {len(sharing) - 1} more" if len(sharing) > 1 else "")
            + ")",
            flush=True,
        )
    meta = {
        "model": model,
        "promptId": report.prompt_id,
        "promptSha256": report.prompt_sha256,
        "settings": recorded_settings(model),
        "stoppedOnRateLimit": report.stopped_on_rate_limit,
        "stopReason": report.stop_reason,
        "claimsVerified": report.claims_verified,
        "claimsRefused": report.claims_refused,
        "textsSha256": hashlib.sha256(json.dumps(sorted(texts.items())).encode()).hexdigest(),
        "updatesAnalysed": len(updates),
        "casesSharingAnUpdate": {
            sharing[0].case_id: [case.case_id for case in sharing[1:]]
            for sharing in cases_of.values()
            if len(sharing) > 1
        },
    }
    return {"votes": recorded, "changelog": meta}, True


def main(argv: list[str] | None = None) -> int:
    from .__main__ import load_cases

    parser = argparse.ArgumentParser(prog="python -m c4.eval.changelog_pass", description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--votes", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--studies", type=Path, default=Path("studies"))
    parser.add_argument(
        "--cache", type=Path, default=Path.home() / ".cache" / "sdlc-c4" / "votes-registry"
    )
    parser.add_argument(
        "--texts", type=Path, default=Path.home() / ".cache" / "sdlc-c4" / "study-notes"
    )
    args = parser.parse_args(argv)
    source = json.loads(args.votes.read_text())
    wanted = set(source["votes"])
    cases = [case for case in load_cases(args.cases) if case.case_id in wanted]
    print(f"{len(cases)} cases, model {MODEL}")
    from .votes import REPORTS

    result, finished = asyncio.run(
        run(
            cases,
            source["votes"],
            args.studies,
            cache=args.cache,
            texts_dir=args.texts,
            reports=REPORTS / args.votes.stem,
        )
    )
    if not finished:
        return 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                **source,
                "votes": result["votes"],
                "changelog": {
                    **result["changelog"],
                    "recordedOn": date.today().isoformat(),
                    "commit": _commit(),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
