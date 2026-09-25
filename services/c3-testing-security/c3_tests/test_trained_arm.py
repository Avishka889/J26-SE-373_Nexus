"""The trained arm, without a trained model.

The weights are trained on Colab and are not in this repository, so what is
tested here is everything around them: the method extraction that decides what
the model is asked about, the process boundary that keeps torch out of this
environment, and the refusal that makes a missing model a failure rather than a
clean scan.

The model itself is replaced by a script that answers from a fixture. That is
not a weaker test than loading real weights: the question is whether this
module reports what it was told, and a stub that says exactly what the protocol
allows answers it precisely.
"""

import json
import textwrap
from pathlib import Path

from c3.detect.trained import Method, ModelProcess, TrainedArm, methods_of

JAVA = textwrap.dedent(
    """\
    package com.example;

    public class Accounts
    {
        public static String findByName(Connection db, String name) throws SQLException
        {
            Statement statement = db.createStatement();
            return statement.executeQuery("select * from users where name = '" + name + "'");
        }

        public static String hash(String password) throws Exception
        {
            return MessageDigest.getInstance("MD5").digest(password.getBytes()).toString();
        }
    }
    """
)


def _repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Accounts.java").write_text(JAVA)
    (tmp_path / "src" / "app.ts").write_text("export const x = 1;\n")
    return tmp_path


def _stub(tmp_path, answers: list[dict], *, greeting: dict | None = None) -> Path:
    """A model process that answers from a file, without torch.

    The answers are read from JSON rather than baked into the script, because
    a JSON literal is not a Python literal and `true` is not `True`.
    """
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "weights.pt").write_text("not real weights")
    (model_dir / "labels.json").write_text(json.dumps({"classes": ["CWE-89"], "other": "other"}))
    (model_dir / "answers.json").write_text(
        json.dumps({"greeting": greeting or {"ready": True}, "answers": answers})
    )
    (model_dir / "stub.py").write_text(
        textwrap.dedent("""\
        import json, pathlib, sys
        scripted = json.loads((pathlib.Path(__file__).parent / "answers.json").read_text())
        answers = scripted["answers"]
        print(json.dumps(scripted["greeting"]), flush=True)
        for line in sys.stdin:
            if not line.strip():
                continue
            print(json.dumps(answers.pop(0) if answers else {"predictions": []}), flush=True)
        """)
    )
    return model_dir


class _StubProcess(ModelProcess):
    """The same process handling, pointed at the stub instead of the server."""

    def start(self) -> None:
        import subprocess
        import sys

        if not (self.model_dir / "weights.pt").is_file():
            self.failure = f"no trained weights at {self.model_dir}"
            return
        self.process = subprocess.Popen(
            [sys.executable, str(self.model_dir / "stub.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        greeting = self._read()
        if greeting is None or "error" in greeting:
            self.failure = f"the model process did not load: {(greeting or {}).get('error', '')}"
            self.close()


class TestWhatTheModelIsAskedAbout:
    def test_it_asks_about_methods_because_that_is_what_it_learned(self, tmp_path) -> None:
        """A model trained on Juliet's methods and then shown a whole file is
        being asked a question it has never seen."""
        found = methods_of(str(_repo(tmp_path)), ["src/Accounts.java"])

        assert [method.name for method in found] == ["findByName", "hash"]

    def test_every_method_carries_the_line_a_reader_can_open(self, tmp_path) -> None:
        root = _repo(tmp_path)
        lines = JAVA.splitlines()

        found = methods_of(str(root), ["src/Accounts.java"])

        for method in found:
            assert method.name in lines[method.start_line - 1]
            assert method.end_line >= method.start_line

    def test_a_language_it_was_never_trained_on_is_not_asked_about(self, tmp_path) -> None:
        """Asking a Java model about TypeScript produces answers, which is
        worse than producing none."""
        found = methods_of(str(_repo(tmp_path)), ["src/Accounts.java", "src/app.ts"])

        assert {method.path for method in found} == {"src/Accounts.java"}


class TestTalkingToTheProcess:
    def test_a_batch_goes_out_and_the_predictions_come_back(self, tmp_path) -> None:
        model_dir = _stub(tmp_path, [{"predictions": [{"vulnerable": True, "cwe": "CWE-89"}]}])

        with _StubProcess(model_dir) as process:
            answer = process.ask(["public void bad() {}"])

        assert answer == [{"vulnerable": True, "cwe": "CWE-89"}]

    def test_a_process_that_reports_an_error_is_a_failure(self, tmp_path) -> None:
        model_dir = _stub(tmp_path, [], greeting={"error": "no module named torch"})

        with _StubProcess(model_dir) as process:
            assert "no module named torch" in process.failure

    def test_a_missing_model_says_where_the_weights_should_be(self, tmp_path) -> None:
        """The most likely failure by far, since the weights are trained
        elsewhere and copied in by hand."""
        process = ModelProcess(tmp_path / "nothing-here")
        process.start()

        assert "no trained weights" in process.failure
        assert "Colab" in process.failure


class TestTheArmItself:
    async def test_a_missing_model_is_a_failure_and_not_a_clean_scan(self, tmp_path) -> None:
        """An arm that silently reports nothing is indistinguishable from an
        arm that found nothing, and only one of them is a measurement."""
        arm = TrainedArm(model_dir=str(tmp_path / "absent"))

        result = await arm.scan(str(_repo(tmp_path)), ["src/Accounts.java"])

        assert result.candidates == []
        assert result.failures and "no trained weights" in result.failures[0]

    async def test_it_reports_no_tokens_and_no_cost(self, tmp_path) -> None:
        """Two of the three numbers this arm exists to put beside its accuracy.
        The third is offline, and it is not asserted here because it is not an
        assertion."""
        arm = TrainedArm(model_dir=str(tmp_path / "absent"))

        run = (await arm.scan(str(_repo(tmp_path)), ["src/Accounts.java"])).run

        assert run.arm == "trained"
        assert (run.prompt_tokens, run.completion_tokens, run.cost_usd) == (0, 0, 0.0)

    def test_the_offline_claim_is_read_off_the_directory(self, tmp_path) -> None:
        """This arm's headline claim, and a claim the code makes about itself
        without checking is the kind this component exists to refuse. A
        directory with no config and no tokenizer fetches both from the hub on
        first use: that works, and it is not offline."""
        bare = tmp_path / "bare"
        bare.mkdir()
        (bare / "weights.pt").write_text("x")
        (bare / "labels.json").write_text("{}")

        assert TrainedArm(model_dir=str(bare)).offline is False

        for name in ("config.json", "tokenizer_config.json"):
            (bare / name).write_text("{}")

        assert TrainedArm(model_dir=str(bare)).offline is True

    def test_a_caller_can_still_say_so_explicitly(self, tmp_path) -> None:
        """Derived by default, not imposed: a deployment that has the encoder
        cached by other means can say so."""
        assert TrainedArm(model_dir=str(tmp_path), offline=True).offline is True

    async def test_a_partial_copy_names_the_file_that_did_not_arrive(self, tmp_path) -> None:
        """The most likely failure of this handover: the weights are half a
        gigabyte and travel separately from the file that says what their class
        indices mean."""
        half = tmp_path / "half"
        half.mkdir()
        (half / "weights.pt").write_text("x")
        arm = TrainedArm(model_dir=str(half))

        result = await arm.scan(str(_repo(tmp_path)), ["src/Accounts.java"])

        assert "labels.json" in result.failures[0]

    async def test_a_prediction_below_the_threshold_is_not_a_finding(self, tmp_path) -> None:
        """A rule stated by this component, not a number the model chose for
        itself."""
        root = _repo(tmp_path)
        model_dir = _stub(
            tmp_path,
            [
                {
                    "predictions": [
                        {"vulnerable": True, "cwe": "CWE-89", "score": 0.99},
                        {"vulnerable": True, "cwe": "CWE-328", "score": 0.10},
                    ]
                }
            ],
        )
        arm = TrainedArm(model_dir=str(model_dir))

        import c3.detect.trained as module

        original = module.ModelProcess
        module.ModelProcess = _StubProcess
        try:
            result = await arm.scan(str(root), ["src/Accounts.java"])
        finally:
            module.ModelProcess = original

        assert [candidate.cwe for candidate in result.candidates] == ["CWE-89"]
        assert result.candidates[0].raw_score == 0.99

    async def test_the_span_is_the_method_the_model_objected_to(self, tmp_path) -> None:
        root = _repo(tmp_path)
        model_dir = _stub(
            tmp_path,
            [
                {
                    "predictions": [
                        {"vulnerable": True, "cwe": "CWE-89", "score": 0.99},
                        {"vulnerable": False, "cwe": "other", "score": 0.02},
                    ]
                }
            ],
        )
        arm = TrainedArm(model_dir=str(model_dir))

        import c3.detect.trained as module

        original = module.ModelProcess
        module.ModelProcess = _StubProcess
        try:
            result = await arm.scan(str(root), ["src/Accounts.java"])
        finally:
            module.ModelProcess = original

        [candidate] = result.candidates
        source = (root / candidate.path).read_text().splitlines()
        assert "findByName" in source[candidate.start_line - 1]
        assert candidate.end_line > candidate.start_line

    def test_a_candidate_keeps_the_models_own_number_without_using_it(self) -> None:
        """`raw_score` is the model's probability on its own scale. Confidence
        is computed from agreement or from a rule, never authored by the arm
        that produced the finding."""
        from c3.detect.trained import _candidate

        candidate = _candidate(
            Method(name="bad", code="{}", path="a.java", start_line=1, end_line=2),
            {"vulnerable": True, "cwe": "CWE-89", "score": 0.87},
        )

        assert candidate.raw_score == 0.87
        assert "confidence" not in candidate.extra


class TestFindingTheInterpreterThatHasTorch:
    """The process boundary's loose end. Torch is deliberately not in this
    environment, so something has to say where it is, and the first live run
    of the arm failed on exactly that: a complete model directory, a correct
    offline claim, and `No module named torch` from the interpreter that was
    never meant to have it."""

    def test_an_explicit_setting_wins(self, tmp_path, monkeypatch) -> None:
        from c3.detect.trained import PYTHON_VARIABLE, serving_python

        monkeypatch.setenv(PYTHON_VARIABLE, str(tmp_path / "python"))

        assert serving_python() == str(tmp_path / "python")

    def test_a_home_relative_setting_is_expanded(self, monkeypatch) -> None:
        """`~` in an environment variable is a string, not a path, until
        something expands it."""
        from pathlib import Path

        from c3.detect.trained import PYTHON_VARIABLE, serving_python

        monkeypatch.setenv(PYTHON_VARIABLE, "~/somewhere/python")

        assert serving_python() == str(Path.home() / "somewhere" / "python")

    def test_with_nothing_set_it_falls_back_rather_than_refusing(
        self, tmp_path, monkeypatch
    ) -> None:
        """A deployment that does have torch in its own environment is a
        perfectly good way to run this and should not need a variable to say
        so. When neither has it, the process says so clearly."""
        import sys

        from c3.detect import trained as module

        monkeypatch.delenv(module.PYTHON_VARIABLE, raising=False)
        monkeypatch.setattr(module, "DEFAULT_PYTHON", str(tmp_path / "absent" / "python"))

        assert module.serving_python() == sys.executable
