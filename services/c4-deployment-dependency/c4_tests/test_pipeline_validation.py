"""Validation on first generation (NFR5), each check shown to catch what it is for.

Every check gets one planted defect of the kind it exists to find, in a file
generated for the platform's own task tracker, and must fail that file for that
reason. The linters run in their pinned images and are marked `docker`; the
schemas, the YAML reading and the secret scan run anywhere.
"""

from datetime import UTC, datetime

import pytest
import yaml
from c4.pipeline.generate import generate
from c4.pipeline.validate import SECRET_RULES, parse_yaml, secret_scan, validate
from sdlc_contracts import PipelineFile

from .docker import needs_docker
from .test_pipeline_generation import CONTRACT, ROUTER, SUPERTEST, TRACKER, UPDATES, _scripted

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def _generated(**settings) -> dict[str, tuple[str, str]]:
    generated = generate(
        TRACKER,
        UPDATES,
        stack_id="mern",
        contract=CONTRACT,
        included=[SUPERTEST.id, ROUTER.id],
        settings={"project_slug": "task-tracker", **settings},
        version=2,
        code_version=3,
        now=NOW,
        resolver=_scripted(),
        validate=lambda files: {},
    )
    return {f.path: (f.purpose, generated.layer[f.path]) for f in generated.config.files}


FILES = _generated(kubernetes=True)


def _planted(path: str, old: str, new: str) -> dict[str, tuple[str, str]]:
    purpose, text = FILES[path]
    assert old in text, f"the defect cannot be planted: {old!r} is not in {path}"
    return {path: (purpose, text.replace(old, new, 1))}


def _verdict(checked: dict, path: str, validator: str):
    [verdict] = [v for v in checked[path] if v.validator == validator]
    return verdict


NO_DOCKER = "docker is not installed"


class TestTheSchemas:
    def test_a_render_plan_render_does_not_offer_is_refused(self) -> None:
        checked = validate(
            _planted("render.yaml", "plan: free", "plan: gratis"), docker_reason=NO_DOCKER
        )
        verdict = _verdict(checked, "render.yaml", "json-schema")
        assert verdict.outcome == "failed"
        assert any(finding.startswith("services/0/plan") for finding in verdict.findings)
        assert verdict.schema_url == "https://render.com/schema/render.yaml.json"
        assert verdict.schema_retrieved == "2026-09-27"

    def test_a_vercel_rewrite_list_that_is_not_a_list_is_refused(self) -> None:
        purpose, text = FILES["vercel.json"]
        broken = text.replace('"rewrites": [', '"rewrites": "everything", "was": [', 1)
        checked = validate({"vercel.json": (purpose, broken)}, docker_reason=NO_DOCKER)
        verdict = _verdict(checked, "vercel.json", "json-schema")
        assert verdict.outcome == "failed"
        assert any(finding.startswith("rewrites") for finding in verdict.findings)

    def test_a_workflow_without_jobs_is_refused(self) -> None:
        path = ".github/workflows/verify-release.yml"
        checked = validate(_planted(path, "jobs:", "steps:"), docker_reason=NO_DOCKER)
        verdict = _verdict(checked, path, "json-schema")
        assert verdict.outcome == "failed"
        assert any("'jobs' is a required property" in finding for finding in verdict.findings)

    def test_a_fingerprint_that_is_not_a_hash_is_refused(self) -> None:
        path = "apps/web/public/release.json"
        _, text = FILES[path]
        digest = text.split('"candidateHash": "')[1][:64]
        checked = validate(_planted(path, digest, "abc"), docker_reason=NO_DOCKER)
        assert _verdict(checked, path, "json-schema").outcome == "failed"


class TestYamlIsReadAsTheHostsReadIt:
    def test_on_is_a_key_and_off_is_a_word(self) -> None:
        workflow = parse_yaml(FILES[".github/workflows/deploy.yml"][1])
        assert "on" in workflow and True not in workflow
        assert parse_yaml("trigger: off\n") == {"trigger": "off"}
        assert yaml.safe_load("trigger: off\n") == {"trigger": False}

    def test_a_key_written_twice_is_refused(self) -> None:
        checked = validate(
            _planted("render.yaml", "plan: free", "plan: free\n    plan: starter"),
            docker_reason=NO_DOCKER,
        )
        verdict = _verdict(checked, "render.yaml", "yaml-parse")
        assert verdict.outcome == "failed" and "written twice" in verdict.findings[0]


class TestTheSecretScan:
    TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"

    def test_a_token_pasted_into_a_workflow_is_found_and_not_repeated(self) -> None:
        path = ".github/workflows/deploy.yml"
        checked = validate(
            _planted(
                path, "VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}", f"VERCEL_TOKEN: {self.TOKEN}"
            ),
            docker_reason=NO_DOCKER,
        )
        verdict = _verdict(checked, path, "secret-scan")
        assert verdict.outcome == "failed"
        assert all(self.TOKEN not in finding for finding in verdict.findings)
        assert any(finding.endswith("a GitHub token") for finding in verdict.findings)

    @pytest.mark.parametrize(
        ("line", "rule"),
        [
            ("token: ghp_" + "x" * 36, "a GitHub token"),
            ("t: github_pat_" + "A1" * 20, "a GitHub fine grained token"),
            ("key: rnd_" + "Ab3" * 8, "a Render API key"),
            ("hook: https://api.render.com/deploy/srv-abc123?key=Zx9_q", "a Render deploy hook"),
            ("id: AKIA" + "ABCD1234EFGH5678", "an AWS access key"),
            ("-----BEGIN OPENSSH PRIVATE KEY-----", "a private key"),
            (
                "MONGODB_URL=mongodb+srv://app:hunter22@cluster0.example.net",
                "a URL with a password",
            ),
            ("jwt: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJlLXZhbHVl", "a JSON web"),
            ("VERCEL_TOKEN: 9fJ2kL0pQ8rS7tU6vW5x", "a value assigned to a name"),
        ],
    )
    def test_each_rule_finds_its_own_shape(self, line: str, rule: str) -> None:
        verdict = secret_scan(f"first: line\n{line}\n")
        assert verdict.outcome == "failed"
        assert any(finding.startswith("line 2: " + rule) for finding in verdict.findings)

    def test_references_through_the_hosts_secret_stores_are_not_values(self) -> None:
        for path in (".github/workflows/deploy.yml", "render.yaml"):
            assert secret_scan(FILES[path][1]).outcome == "passed"
        assert len(SECRET_RULES) == 9


class TestWithoutDocker:
    def test_the_linters_are_not_run_and_the_files_are_unverified(self) -> None:
        checked = validate(FILES, docker_reason=NO_DOCKER)
        for path, validator in (
            ("Dockerfile", "hadolint"),
            (".github/workflows/deploy.yml", "actionlint"),
            ("k8s/deployment.yaml", "kubeconform"),
        ):
            verdict = _verdict(checked, path, validator)
            assert verdict.outcome == "not-run" and NO_DOCKER in verdict.reason
        dockerfile = PipelineFile(
            path="Dockerfile",
            purpose="container",
            sha256="0" * 64,
            bytes=1,
            template_id="mern/Dockerfile@2",
            validations=checked["Dockerfile"],
        )
        assert not dockerfile.valid
        assert all(v.outcome == "passed" for v in checked["render.yaml"])


@pytest.mark.docker
@needs_docker
class TestTheLinters:
    def test_every_generated_file_passes_every_check_on_first_generation(self) -> None:
        checked = validate(FILES)
        for path, verdicts in checked.items():
            assert verdicts and all(v.outcome == "passed" for v in verdicts), (path, verdicts)
        assert {v.validator for v in checked[".github/workflows/deploy.yml"]} == {
            "yaml-parse",
            "json-schema",
            "actionlint",
            "secret-scan",
        }

    def test_actionlint_finds_an_input_the_workflow_does_not_declare(self) -> None:
        path = ".github/workflows/deploy.yml"
        checked = validate(
            {
                **_planted(path, "REF: ${{ inputs.ref }}", "REF: ${{ inputs.commit }}"),
                ".github/workflows/verify-release.yml": FILES[
                    ".github/workflows/verify-release.yml"
                ],
            }
        )
        verdict = _verdict(checked, path, "actionlint")
        assert verdict.outcome == "failed"
        assert any('"commit" is not defined' in finding for finding in verdict.findings)

    def test_hadolint_finds_a_cd_where_workdir_belongs(self) -> None:
        checked = validate(
            _planted("Dockerfile", "RUN npm run build", "RUN cd /app && npm run build")
        )
        verdict = _verdict(checked, "Dockerfile", "hadolint")
        assert verdict.outcome == "failed"
        assert any("DL3003" in finding for finding in verdict.findings)

    def test_kubeconform_finds_a_replica_count_that_is_not_a_number(self) -> None:
        checked = validate(_planted("k8s/deployment.yaml", "replicas: 1", 'replicas: "one"'))
        verdict = _verdict(checked, "k8s/deployment.yaml", "kubeconform")
        assert verdict.outcome == "failed"
        assert any("statusInvalid" in finding for finding in verdict.findings)
