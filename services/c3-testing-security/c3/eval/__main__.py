"""Run the three way study on a benchmark, from a terminal.

    uv run python -m c3.eval --checkout ~/datasets/owasp-benchmark --arms scanner
    uv run python -m c3.eval --checkout ... --arms scanner,trained --model ~/models/juliet
    uv run python -m c3.eval --benchmark cwe-bench --checkout ~/datasets/cwe-bench-java \
        --sources ~/datasets/cwe-bench-sources --fetch --cwe CWE-22 --limit 10

A command rather than a notebook, because the numbers it prints end up in a
dissertation and the thing that produced them has to be re-runnable by somebody
reading the methodology. Everything it needs is an argument: which arms, which
checkout, which model, which epoch label. Nothing is read from a config file
that a reader would have to find.

The LLM arm has to be asked for twice: named in `--arms` and again in
`--llm-model`. It is the only arm that costs money per run and the only one
whose result belongs to a particular model rather than to a tool version, so a
command that did not name a model does not start it. That is the whole of the
safeguard, and it is deliberately not a default: a default is how a quota gets
spent during a demo by somebody who thought they were running the scanners.
"""

import argparse
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from sdlc_contracts import HealReport

from ..detect import LlmArm, ScannerArm, TrainedArm, build_detector
from ..harness import TargetRepo, sample_root
from ..harness.targets import detect
from .benchmarks import owasp
from .cwe_bench import fetch_project, project, project_slugs
from .healing import as_epoch_row
from .healing import study as healing_study
from .study import Epoch, combine_studies, run_study
from .tables import build as build_tables


def lend_maven_wrapper(checkout: Path) -> bool:
    """Put this repository's Maven wrapper into a checkout that has none.

    OWASP Benchmark has a `pom.xml` and no wrapper, and Maven is not installed
    on this machine, so without this the bytecode arm cannot be measured on the
    one corpus with real entry points. Copying the wrapper in is an ordinary
    thing to do to a checkout and a rude thing to do silently, which is why it
    is a flag rather than a fallback inside the scanner.
    """
    if (checkout / "mvnw").is_file() and (checkout / ".mvn" / "wrapper").is_dir():
        return False
    source = sample_root("java-sample")
    for name in ("mvnw", "mvnw.cmd"):
        if (source / name).is_file():
            shutil.copy2(source / name, checkout / name)
            (checkout / name).chmod(0o755)
    # The wrapper subdirectory, not the whole of `.mvn`: a real project keeps
    # its own `jvm.config` and extensions in there, and replacing the directory
    # would silently change how the project builds. Copying past that mistake
    # once produced a wrapper that could not find its own properties file.
    wrapper = source / ".mvn" / "wrapper"
    if wrapper.is_dir():
        target = checkout / ".mvn" / "wrapper"
        target.mkdir(parents=True, exist_ok=True)
        for item in wrapper.iterdir():
            if item.is_file():
                shutil.copy2(item, target / item.name)
    return (checkout / "mvnw").is_file() and (checkout / ".mvn" / "wrapper").is_dir()


#: The ground truth file, which sits with the reports and is not one.
LABELS_FILE = "labels.json"


def _run_healing_study(arguments) -> None:
    """Contribution B's numbers, from the heal reports a run stored.

    Separate from the detection study rather than a mode of it, because they
    measure different claims and share nothing but the epoch discipline. A
    single command that did both would have to be told which one it was doing
    anyway.
    """
    directory = Path(arguments.healing).expanduser()
    files = sorted(directory.glob("*.json")) if directory.is_dir() else [directory]
    # The labels live beside the reports they are about, which is where a
    # reader looks for them, so the one file in that directory that is not a
    # report is named rather than guessed at.
    files = [file for file in files if file.name != LABELS_FILE]
    if not files:
        raise SystemExit(f"no heal reports in {directory}")

    reports = []
    for file in files:
        body = json.loads(file.read_text())
        # A stored artefact carries the report as its body; a file written by
        # hand for a study may be the report itself.
        reports.append(HealReport.model_validate(body.get("body", body)))
    print(f"read {len(reports)} report{'s' if len(reports) != 1 else ''} from {directory}")

    labels = (
        json.loads(Path(arguments.labels).expanduser().read_text()) if arguments.labels else None
    )
    found = healing_study(reports, labels=labels)

    print(found.table())
    if not labels:
        print()
        print(
            "no labels were given, so classification is not scored. Scoring the loop "
            "against its own verdicts would measure its consistency, not its correctness."
        )

    if arguments.out:
        Path(arguments.out).write_text(
            json.dumps(
                as_epoch_row(
                    found,
                    label=arguments.epoch or "unlabelled",
                    commit=arguments.commit,
                ),
                indent=2,
            )
            + "\n"
        )
        print(f"\nwrote {arguments.out}")


def _repo(root: Path) -> TargetRepo:
    stack, apps, detected_by = detect(root)
    return TargetRepo(root=root, kind="benchmark", stack=stack, apps=apps, detected_by=detected_by)


#: Which arms this command knows how to build.
ARMS = ("scanner", "trained", "llm")


def _check_arms(wanted: list[str], arguments, parser) -> None:
    """Every argument checked before anything is constructed.

    Order matters here and it took a wrong answer to notice: building the arms
    as they were validated meant the llm arm's agent was constructed first,
    which needs a provider key, so a command missing `--model` for the trained
    arm reported a missing OpenRouter key instead. A reader debugging that is
    being told about the wrong arm.
    """
    for name in wanted:
        if name not in ARMS:
            parser.error(f"{name!r} is not an arm this command runs. Known arms: {', '.join(ARMS)}")
    if "trained" in wanted and not arguments.model:
        parser.error("the trained arm needs --model, the directory Colab produced")
    if "llm" in wanted and not arguments.llm_model:
        parser.error(
            "the llm arm needs --llm-model, named rather than defaulted. A study whose model "
            "was picked by a default cannot say which model it used"
        )


def _projects(arguments, parser) -> list:
    """The benchmarks to run over: one for OWASP, one per project otherwise.

    CWE-Bench-Java is scored per project because that is what it is: 120
    separate repositories with one CVE each. Running an arm over all of them at
    once would be running it over 120 unrelated codebases and averaging.
    """
    checkout = Path(arguments.checkout).expanduser()
    if arguments.benchmark == "owasp":
        if arguments.lend_maven_wrapper:
            lent = lend_maven_wrapper(checkout)
            print(
                f"lent the Maven wrapper: {lent}" if lent else "the checkout already has a wrapper"
            )
        return [owasp(checkout)]

    sources = Path(arguments.sources or (checkout.parent / "cwe-bench-sources")).expanduser()
    slugs = project_slugs(checkout, cwe=arguments.cwe, limit=arguments.limit)
    found = []
    skipped: list[str] = []
    for slug in slugs:
        if arguments.fetch:
            try:
                fetch_project(checkout, slug, sources)
            except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                # A project that will not fetch is a project this run did not
                # measure, and saying so is the whole point. It is not a
                # project with no weaknesses in it.
                print(f"could not fetch {slug}: {error}")
                skipped.append(slug)
                continue
        if not (sources / slug).is_dir():
            print(f"skipping {slug}: not fetched. Add --fetch to get it.")
            skipped.append(slug)
            continue
        found.append(project(checkout, slug, sources))
    if skipped:
        print(f"{len(skipped)} of {len(slugs)} projects were not measured: {', '.join(skipped)}")
    return found


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", default="", help="the benchmark checkout")
    parser.add_argument(
        "--healing",
        default="",
        help=(
            "a directory of stored heal reports, to run the self healing study instead of "
            "the detection one"
        ),
    )
    parser.add_argument(
        "--labels",
        default="",
        help=(
            "json mapping a test id to what a person decided it really was, brittle or "
            "regression. Without it the convergence and refusal figures are still produced "
            "and only the classification score is skipped"
        ),
    )
    parser.add_argument(
        "--tables",
        default="",
        help=(
            "a directory of stored studies, to format them as the dissertation's tables "
            "instead of running anything. Reads what is on disk and computes nothing, so a "
            "table cannot disagree with the artefact it came from"
        ),
    )
    parser.add_argument("--benchmark", default="owasp", choices=("owasp", "cwe-bench"))
    parser.add_argument("--arms", default="scanner", help="comma separated: scanner, trained, llm")
    parser.add_argument("--model", default="", help="the trained model directory")
    parser.add_argument(
        "--llm-model",
        default="",
        help=(
            "the exact model id for the llm arm, such as "
            "openrouter:some-vendor/some-model:free. Required rather than defaulted: this arm "
            "is the one that costs money per run and the one whose result belongs to a "
            "specific model, so it is never started by a command that did not name one"
        ),
    )
    parser.add_argument("--epoch", default="", help="a label for this run's epoch")
    parser.add_argument("--commit", default="", help="the commit these numbers came from")
    parser.add_argument("--out", default="", help="where to write the study json")
    parser.add_argument("--limit", type=int, default=0, help="first N projects or files")
    parser.add_argument("--cwe", default="", help="cwe-bench: one weakness class only")
    parser.add_argument("--sources", default="", help="cwe-bench: where projects are fetched")
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="cwe-bench: fetch the projects that are missing, at their buggy commit",
    )
    parser.add_argument(
        "--lend-maven-wrapper",
        action="store_true",
        help=(
            "copy this repository's Maven wrapper into the checkout so the bytecode arm "
            "can build it. A deliberate modification of somebody else's checkout, so it "
            "is a flag a person types rather than something a scanner does quietly."
        ),
    )
    arguments = parser.parse_args()

    if arguments.tables:
        written = build_tables(Path(arguments.tables).expanduser())
        if arguments.out:
            Path(arguments.out).expanduser().write_text(written)
            print(f"wrote {arguments.out}")
        else:
            print(written)
        return

    if arguments.healing:
        _run_healing_study(arguments)
        return

    if not arguments.checkout:
        parser.error("--checkout is required for the detection study")

    benchmarks = _projects(arguments, parser)
    if not benchmarks:
        parser.error("nothing to run over: no project was fetched or matched")

    wanted_arms = [name.strip() for name in arguments.arms.split(",") if name.strip()]
    _check_arms(wanted_arms, arguments, parser)
    studies = []
    for benchmark in benchmarks:
        files = (
            benchmark.files[: arguments.limit]
            if arguments.benchmark == "owasp" and arguments.limit
            else benchmark.files
        )
        wanted = set(files)
        truth = [span for span in benchmark.truth if span.path in wanted]
        repo = _repo(benchmark.root)
        detectors = []
        for name in wanted_arms:
            if name == "scanner":
                detectors.append(ScannerArm(repo=repo))
            elif name == "trained":
                detectors.append(TrainedArm(model_dir=arguments.model))
            elif name == "llm":
                detectors.append(
                    LlmArm(
                        agent=build_detector(arguments.llm_model),
                        model_id=arguments.llm_model,
                    )
                )
        epoch = Epoch(
            label=arguments.epoch or "unlabelled",
            commit=arguments.commit,
            dataset=benchmark.epoch_note,
            note=f"{len(files)} files of {len(benchmark.files)}",
        )
        studies.append(
            await run_study(
                detectors, str(benchmark.root), files, truth, epoch=epoch, target=benchmark.name
            )
        )
        if len(benchmarks) > 1:
            row = studies[-1].arms[0]
            print(
                f"{benchmark.name}: {row.found} findings, {len(truth)} real, "
                f"macro F1 {row.scorecard.macro_f1:.3f}"
            )

    epoch = Epoch(
        label=arguments.epoch or "unlabelled",
        commit=arguments.commit,
        dataset=(
            benchmarks[0].epoch_note
            if len(benchmarks) == 1
            else f"{len(benchmarks)} projects of CWE-Bench-Java, MIT seed data"
        ),
        note=f"{sum(len(b.files) for b in benchmarks)} files",
    )
    study = (
        studies[0]
        if len(studies) == 1
        else combine_studies(
            studies, epoch=epoch, target=f"CWE-Bench-Java, {len(studies)} projects"
        )
    )

    print()
    print(study.table())
    print()
    for arm in study.arms:
        failures = f"{len(arm.failures)} tools did not run" if arm.failures else "no failures"
        print(f"{arm.arm}: {arm.found} findings, {arm.refused} refused, {failures}")
        for failure in dict.fromkeys(arm.failures[:2]):
            print(f"    {failure[:160]}")
    print()
    print(f"{'cwe':10} {'support':>8} {'precision':>10} {'recall':>8} {'f1':>7}")
    for arm in study.arms:
        print(f"-- {arm.arm}")
        for row in arm.scorecard.as_dict()["perClass"]:
            print(
                f"{row['cwe']:10} {row['support']:8} {row['precision']:10.3f} "
                f"{row['recall']:8.3f} {row['f1']:7.3f}"
            )

    if arguments.out:
        study.write(arguments.out)
        print(f"\nwrote {arguments.out}")
    else:
        print()
        print(json.dumps({"epoch": study.epoch.label, "target": study.target}))


if __name__ == "__main__":
    asyncio.run(main())
