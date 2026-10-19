"""The locally trained model as a detector, and the only arm that works unplugged.

The third arm, and the one whose case is made mostly of the operational half of
the study rather than of accuracy. It runs on this machine, with the network
down, at no cost per method, at the same speed on the thousandth file as on the
first. Whether it is also more accurate is the question the comparison answers;
these four properties are true before the comparison starts, and an interface
that reported only F1 could not see any of them.

**It speaks to a process rather than importing one.** Torch and transformers
are two gigabytes of wheels and this machine has under six of memory, so the
model lives in its own interpreter and this module talks to it over a pipe. The
boundary keeps the orchestrator's environment small, keeps CI free of a GPU
stack it would never use, and makes the offline claim concrete: it is a thing
that can be started on a machine with no network.

**It works at method granularity, because that is what it was trained on.** A
model trained on Juliet's methods and then shown a whole file would be asked a
question it has never seen. So the arm extracts methods, asks about each one,
and reports the span of the method the model objected to, which is also the
span a reader wants.

**A model that is not there is a failure, not a clean scan.** No weights, no
torch, a process that would not start: all of those produce a failure on the
result, never an empty finding list. An arm that silently reports nothing is
indistinguishable from an arm that found nothing, and only one of them is a
measurement.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from sdlc_contracts import DetectorRun

from ..detection import Arm, Candidate, DetectionResult
from ..ml.juliet import methods_in
from .severity import normalise

log = logging.getLogger(__name__)

#: How many methods travel in one request. Large enough to keep the pipe busy,
#: small enough that a pathological file cannot build a gigabyte of JSON.
BATCH = 16

#: How long to wait for the model to load before deciding it will not. A cold
#: start pulls the base encoder from the local cache and builds the graph.
START_TIMEOUT_SECONDS = 180.0
ANSWER_TIMEOUT_SECONDS = 300.0

#: The server, as a file path. Launched as a script rather than as
#: `-m c3.ml.serve`, because the interpreter that has torch is by construction
#: not the one that has this package installed: the module form worked in the
#: workspace venv and failed the moment it was pointed at the real serving
#: environment. `serve.py` imports nothing from this repository, which is what
#: makes running it as a loose file correct rather than a workaround.
SERVER = Path(__file__).resolve().parents[1] / "ml" / "serve.py"

#: Which interpreter serves the model. The whole point of the process
#: boundary is that torch does not live in this environment, so the default
#: interpreter is exactly the one that cannot serve it: this names the other
#: one. Set it once and every stage that reaches the trained arm finds it.
PYTHON_VARIABLE = "C3_MODEL_PYTHON"

#: Where the serving environment is put when nobody says otherwise. Outside
#: the repository, beside the weights it exists to load, and deliberately not
#: in the workspace venv: two gigabytes of wheels there would reach CI and
#: every developer's machine for the sake of one arm of one comparison.
DEFAULT_PYTHON = "~/venvs/c3-torch/bin/python"

#: What has to be in the model directory before the arm can run at all.
REQUIRED = ("weights.pt", "labels.json")

#: What has to be there as well before the arm can honestly claim to run with
#: the network unplugged. Without these the encoder and the tokenizer are
#: fetched from the hub on first use, which works and is not offline.
SELF_CONTAINED = ("config.json", "tokenizer_config.json")

#: Only the languages the model was trained on. Asking a Java model about
#: TypeScript would produce answers, which is worse than producing none.
SUFFIXES = (".java",)


@dataclass(frozen=True)
class Method:
    """One method, and where it is in the file it came from."""

    name: str
    code: str
    path: str
    start_line: int
    end_line: int


def methods_of(root: str, files: list[str]) -> list[Method]:
    """Every method in the files this arm can read, with its span.

    The span is computed by counting newlines to the method's offset rather
    than by asking the parser, because the parser works on text and the report
    needs a line a reader can open.
    """
    found: list[Method] = []
    for path in files:
        if not path.endswith(SUFFIXES):
            continue
        try:
            source = (Path(root) / path).read_text(errors="replace")
        except OSError:
            continue
        for name, code in methods_in(source):
            offset = source.find(code)
            start = source.count("\n", 0, offset) + 1 if offset >= 0 else 1
            found.append(
                Method(
                    name=name,
                    code=code,
                    path=path,
                    start_line=start,
                    end_line=start + code.count("\n"),
                )
            )
    return found


def serving_python() -> str:
    """The interpreter that has torch in it, or this one.

    Falls back to the current interpreter rather than refusing, because a
    deployment that does have torch in its own environment is a perfectly good
    way to run this and should not need to set a variable to say so. When
    neither has it, the process says `No module named torch` and that is a
    clear enough failure to act on.
    """
    named = os.environ.get(PYTHON_VARIABLE, "").strip()
    if named:
        return str(Path(named).expanduser())
    default = Path(DEFAULT_PYTHON).expanduser()
    return str(default) if default.is_file() else sys.executable


class ModelProcess:
    """The trained model, running beside this one.

    Started lazily and closed by the context manager, so a stage that never
    reaches the trained arm never pays two gigabytes for it.
    """

    def __init__(self, model_dir: str | Path, *, python: str | None = None) -> None:
        self.model_dir = Path(model_dir)
        self.python = python or serving_python()
        self.process: subprocess.Popen | None = None
        self.failure = ""

    def __enter__(self) -> "ModelProcess":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        missing = [name for name in REQUIRED if not (self.model_dir / name).is_file()]
        if missing:
            # Named one by one rather than as "something is wrong", because the
            # most likely failure here is a partial copy: the weights are half
            # a gigabyte and travel separately from the file that says what
            # their class indices mean.
            self.failure = (
                f"no trained weights at {self.model_dir}: missing {', '.join(missing)}. "
                "Train them on Colab with c3/ml/train.py and copy the whole output "
                "directory here."
            )
            return
        try:
            self.process = subprocess.Popen(
                [self.python, str(SERVER), "--model", str(self.model_dir)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as error:
            self.failure = f"the model process would not start: {error}"
            return
        greeting = self._read()
        if greeting is None or "error" in greeting:
            # A child that died before its first line has said everything it is
            # going to say on stderr, and "it said nothing" is not a fault
            # report anybody can act on. The first time this happened the real
            # cause was a missing package name in a traceback nobody read.
            detail = (greeting or {}).get("error") or self._last_words()
            self.failure = f"the model process did not load: {detail}"
            self.close()

    def _last_words(self) -> str:
        """Whatever the child printed on its way out."""
        if self.process is None or self.process.stderr is None:
            return "it said nothing"
        try:
            said = self.process.stderr.read() or ""
        except OSError:
            return "it said nothing and its error stream could not be read"
        lines = [line for line in said.strip().splitlines() if line.strip()]
        return lines[-1][:300] if lines else "it said nothing"

    def _read(self) -> dict | None:
        if self.process is None or self.process.stdout is None:
            return None
        line = self.process.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"error": f"unreadable answer: {line[:200]}"}

    def ask(self, methods: list[str]) -> list[dict]:
        """One batch, or an empty list and a failure recorded."""
        if self.process is None or self.process.stdin is None:
            return []
        try:
            self.process.stdin.write(json.dumps({"methods": methods}) + "\n")
            self.process.stdin.flush()
        except OSError as error:
            self.failure = f"the model process closed the pipe: {error}"
            return []
        answer = self._read()
        if answer is None:
            self.failure = "the model process stopped answering"
            return []
        if "error" in answer:
            self.failure = f"the model process refused a batch: {answer['error']}"
            return []
        return list(answer.get("predictions") or [])

    def close(self) -> None:
        """Close the pipe, which is how the child is told to stop.

        Every pipe, not just the one it reads: an unclosed stdout leaks a file
        descriptor per scan, and a stage that scans a hundred versions would
        run out of them long after the cause stopped being visible.
        """
        if self.process is None:
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=10)
        finally:
            for pipe in (self.process.stdout, self.process.stderr):
                if pipe is not None:
                    pipe.close()
            self.process = None


@dataclass
class TrainedArm:
    """GraphCodeBERT fine tuned on Juliet, behind the detector interface."""

    model_dir: str
    model_id: str = ""
    arm: Arm = "trained"
    #: Whether this arm really runs with the network unplugged. Derived from
    #: what is actually in the directory rather than asserted, because it is
    #: this arm's headline claim and a claim the code makes about itself
    #: without checking is the kind this component exists to refuse. A
    #: directory with no config and no tokenizer fetches both from the hub on
    #: first use: that works, and it is not offline.
    offline: bool | None = None
    #: Below this the model is not confident enough to be worth a reader's
    #: time. A rule, stated here, not a number the model chose for itself.
    threshold: float = 0.5
    failures: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.offline is None:
            directory = Path(self.model_dir)
            self.offline = all((directory / name).is_file() for name in SELF_CONTAINED)
        if not self.model_id:
            run = Path(self.model_dir) / "run.json"
            trained = json.loads(run.read_text()).get("baseModel", "") if run.is_file() else ""
            self.model_id = (
                f"{trained} fine tuned, {Path(self.model_dir).name}"
                if trained
                else f"trained model at {Path(self.model_dir).name}"
            )

    async def scan(self, root: str, files: list[str]) -> DetectionResult:
        """On a worker thread, as the scanner arm runs: loading the model and
        waiting on each batch's answer are blocking reads of a child process."""
        return await asyncio.to_thread(self.scan_now, root, files)

    def scan_now(self, root: str, files: list[str]) -> DetectionResult:
        started = datetime.now(UTC)
        clock = monotonic()
        methods = methods_of(root, files)
        candidates: list[Candidate] = []
        self.failures = []

        with ModelProcess(self.model_dir) as process:
            if process.failure:
                self.failures.append(process.failure)
            else:
                for index in range(0, len(methods), BATCH):
                    batch = methods[index : index + BATCH]
                    predictions = process.ask([method.code for method in batch])
                    if len(predictions) != len(batch):
                        if process.failure:
                            self.failures.append(process.failure)
                        break
                    candidates.extend(
                        _candidate(method, prediction)
                        for method, prediction in zip(batch, predictions, strict=True)
                        if prediction.get("vulnerable")
                        and float(prediction.get("score") or 0) >= self.threshold
                    )

        return DetectionResult(
            candidates=[candidate for candidate in candidates if candidate is not None],
            failures=list(self.failures),
            units_examined=len(methods),
            run=DetectorRun(
                arm="trained",
                model_id=self.model_id,
                started_at=started,
                duration_seconds=round(monotonic() - clock, 3),
                # No API, so no tokens and a cost that is known to be nothing.
                # This is the arm those three zeros are the argument for.
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=0.0,
                offline=self.offline,
                files_scanned=len({method.path for method in methods}),
            ),
        )


def _candidate(method: Method, prediction: dict) -> Candidate:
    cwe = normalise(str(prediction.get("cwe") or "")) or "CWE-0"
    return Candidate(
        cwe=cwe,
        title=f"{cwe} in {method.name}",
        path=method.path,
        start_line=method.start_line,
        end_line=method.end_line,
        message=f"the trained model classified {method.name} as {cwe}",
        # Its own probability, on its own scale, kept and never used as
        # confidence: confidence is computed from agreement or from a rule.
        raw_score=float(prediction.get("score") or 0.0),
        extra={"method": method.name},
    )
