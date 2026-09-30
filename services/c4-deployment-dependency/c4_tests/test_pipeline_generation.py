"""Pipeline generation on the platform's own generated project.

The task tracker in `studies/clients/` is filled into every MERN template and
compared with golden files, so any change to what is generated is a change
someone saw. The dependency resolution is scripted here (the real one asks npm
and is marked `sandbox`), and nothing is validated yet in these tests: what is
checked is what was generated, for which project, and what it refers to.

Regenerate the golden files after a deliberate template change, with a new
template version, by running this file with `C4_REGENERATE_GOLDEN=1`.
"""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from c4.eval.loaders.clients import read_client
from c4.pipeline import render
from c4.pipeline.candidate import Resolution, candidate_hash, resolve
from c4.pipeline.generate import CHECKOUT, generate, smoke_paths
from c4.pipeline.validate import validate
from sdlc_contracts import (
    ApiContract,
    DependencyUpdate,
    DependencyUpdates,
    update_id_for,
    update_key,
)

HERE = Path(__file__).parent
STUDIES = HERE.parent / "studies"
GOLDEN = HERE / "fixtures" / "pipeline" / "mern-task-tracker"
BASELINE = (STUDIES / "pins" / "task-tracker-2026-06-01.package-lock.json").read_text()
TRACKER = {
    **read_client(STUDIES / "clients" / "task-tracker"),
    "package-lock.json": BASELINE,
}
CONTRACT = ApiContract.model_validate(
    json.loads((HERE / "fixtures" / "sag" / "contract.json").read_text())
)
NOW = datetime(2026, 9, 27, tzinfo=UTC)
SETTINGS = {"project_slug": "task-tracker"}


def _update(
    package: str, old: str, new: str, manifest: str, *, also: tuple[str, ...] = ()
) -> DependencyUpdate:
    key = update_key("npm", package, old, new)
    return DependencyUpdate(
        id=update_id_for(key),
        key=key,
        ecosystem="npm",
        package=package,
        manifest_path=manifest,
        also_declared_in=list(also),
        scope="prod",
        declared=old,
        from_version=old,
        to_version=new,
        candidate="latest",
        change="minor",
    )


SUPERTEST = _update("supertest", "7.2.2", "7.3.0", "apps/api/package.json")
ROUTER = _update("react-router-dom", "7.16.0", "7.18.4", "apps/web/package.json")
UPDATES = DependencyUpdates(
    version=1,
    generated_at=NOW,
    code_version=3,
    test_version=1,
    target="generated",
    updates=[SUPERTEST, ROUTER],
)


def _scripted(*, refuse: set[str] = frozenset()):
    def resolver(files, updates):
        return Resolution(
            lockfile=files["package-lock.json"],
            applied=[u.id for u in updates if u.id not in refuse],
            refused={u.id: "npm could not apply it: ERESOLVE" for u in updates if u.id in refuse},
            resolved_by="scripted",
        )

    return resolver


def _no_linters(files):
    """The schemas and the secret scan, which need nothing; the linters have their own tests."""
    return validate(files, docker_reason="not run in the generation tests")


def _generate(files=TRACKER, *, stack_id="mern", settings=SETTINGS, refuse=frozenset(), **kw):
    kw.setdefault("validate", _no_linters)
    return generate(
        files,
        UPDATES,
        stack_id=stack_id,
        contract=CONTRACT,
        included=[SUPERTEST.id, ROUTER.id],
        settings=settings,
        version=2,
        code_version=3,
        now=NOW,
        resolver=_scripted(refuse=refuse),
        **kw,
    )


class TestTheGeneratedFiles:
    def test_the_task_tracker_matches_its_golden_files(self) -> None:
        generated = _generate()
        produced = {f.path: generated.layer[f.path] for f in generated.config.files}
        if os.environ.get("C4_REGENERATE_GOLDEN"):
            for path, text in produced.items():
                target = GOLDEN / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        golden = {
            path.relative_to(GOLDEN).as_posix(): path.read_text()
            for path in GOLDEN.rglob("*")
            if path.is_file()
        }
        assert sorted(produced) == sorted(golden)
        for path, text in produced.items():
            assert text == golden[path], f"{path} differs from its golden file"

    def test_every_file_names_its_template_and_hashes_its_bytes(self) -> None:
        generated = _generate()
        paths = {f.path for f in generated.config.files}
        assert paths == {
            "Dockerfile",
            ".dockerignore",
            "render.yaml",
            "vercel.json",
            ".github/workflows/deploy.yml",
            ".github/workflows/verify-release.yml",
            "apps/web/public/release.json",
        }
        for item in generated.config.files:
            text = generated.layer[item.path]
            assert item.sha256 == hashlib.sha256(text.encode()).hexdigest()
            assert item.template_id in render.manifest()
            assert f"from {item.template_id}" in text or item.path.endswith(".json")

    def test_the_image_runs_the_backends_own_start_command_on_its_port(self) -> None:
        dockerfile = _generate().layer["Dockerfile"]
        assert "WORKDIR /app/apps/api" in dockerfile
        assert 'CMD ["node", "--experimental-strip-types", "src/server.ts"]' in dockerfile
        assert "EXPOSE 3001" in dockerfile
        assert "COPY --from=test /tmp/tested /tmp/tested" in dockerfile
        for workspace in ("apps/api", "apps/web", "packages/contract"):
            assert f"COPY {workspace}/package.json {workspace}/" in dockerfile

    def test_the_workflow_tests_and_builds_in_its_own_stage_before_it_deploys(self) -> None:
        """Dispatched once to test and build the commit, before anything moves
        traffic, and once to deploy the frontend and verify both (review item C4-8)."""
        workflow = yaml.safe_load(_generate().layer[".github/workflows/deploy.yml"])
        stage = workflow[True]["workflow_dispatch"]["inputs"]["stage"]
        assert (stage["type"], stage["options"], stage["required"]) == (
            "choice",
            ["test", "deploy"],
            True,
        )
        jobs = workflow["jobs"]
        assert jobs["test"]["if"] == "inputs.stage == 'test'"
        runs = [step.get("run") for step in jobs["test"]["steps"]]
        assert runs.index("npm test") < runs.index("npm run build")
        assert jobs["frontend"]["if"] == "inputs.stage == 'deploy'"
        assert "needs" not in jobs["frontend"], "the deploy stage runs on a commit already tested"
        assert jobs["verify"]["needs"] == "frontend"

    def test_actions_are_pinned_by_commit(self) -> None:
        deploy = _generate().layer[".github/workflows/deploy.yml"]
        assert f"actions/checkout@{CHECKOUT[0]} # {CHECKOUT[1]}" in deploy
        uses = [line.split("uses: ")[1] for line in deploy.splitlines() if "uses: actions/" in line]
        assert uses and all("@" in use and len(use.split("@")[1].split()[0]) == 40 for use in uses)


class TestSecretsAreNamedNeverValued:
    def test_each_file_lists_the_secret_names_it_refers_to(self) -> None:
        files = {f.path: f for f in _generate().config.files}
        assert files["render.yaml"].secrets_referenced == ["MONGODB_URL"]
        # No Render credential: the platform deploys the backend through Render's API.
        assert files[".github/workflows/deploy.yml"].secrets_referenced == [
            "VERCEL_ORG_ID",
            "VERCEL_PROJECT_ID",
            "VERCEL_TOKEN",
        ]
        assert files["Dockerfile"].secrets_referenced == []

    def test_render_declares_the_secret_and_asks_for_its_value_on_render(self) -> None:
        body = yaml.safe_load(_generate().layer["render.yaml"])
        [service] = body["services"]
        assert service["envVars"] == [{"key": "MONGODB_URL", "sync": False}]
        assert service["autoDeployTrigger"] == "off" and service["plan"] == "free"


class TestWhatTheRepositoryAllows:
    def test_environment_keys_only_where_github_can_enforce_them(self) -> None:
        def jobs(settings):
            workflow = yaml.safe_load(
                _generate(settings=settings).layer[".github/workflows/deploy.yml"]
            )
            return {name: job.get("environment") for name, job in workflow["jobs"].items()}

        # The backend is deployed by the platform through Render's API, so the one
        # job GitHub's reviewers hold is the frontend's.
        assert jobs({**SETTINGS, "github_protection": "configured"}) == {
            "test": None,
            "frontend": "production",
            "verify": None,
        }
        assert set(
            jobs({**SETTINGS, "github_protection": "unavailable-private-repo"}).values()
        ) == {None}

    def test_origins_given_are_used_and_origins_predicted_say_so(self) -> None:
        predicted = _generate()
        assert predicted.notes["origins_predicted"] == ["backend", "frontend"]
        vercel = json.loads(predicted.layer["vercel.json"])
        assert vercel["rewrites"][0] == {
            "source": "/api/:path*",
            "destination": "https://task-tracker-api.onrender.com/:path*",
        }
        given = _generate(settings={**SETTINGS, "backend_origin": "https://tt-x1.onrender.com"})
        assert "https://tt-x1.onrender.com/:path*" in given.layer["vercel.json"]
        assert given.notes["origins_predicted"] == ["frontend"]

    def test_settings_that_could_break_out_of_a_file_are_refused(self) -> None:
        with pytest.raises(ValueError, match="project_slug"):
            _generate(settings={"project_slug": "tt\nname: evil"})


class TestTheFingerprint:
    def test_release_json_carries_the_hash_of_everything_else(self) -> None:
        generated = _generate()
        release = json.loads(generated.layer["apps/web/public/release.json"])
        tree = {**TRACKER, **generated.layer}
        assert release["candidateHash"] == generated.config.candidate_hash
        assert release["candidateHash"] == candidate_hash(
            tree, fingerprint="apps/web/public/release.json"
        )
        assert (release["deployVersion"], release["codeVersion"]) == (2, 3)
        assert release["lockfileSha256"] == hashlib.sha256(BASELINE.encode()).hexdigest()

    def test_any_change_to_the_candidate_moves_the_hash(self) -> None:
        first = _generate().config.candidate_hash
        edited = {**TRACKER, "apps/api/src/app.ts": TRACKER["apps/api/src/app.ts"] + "\n"}
        assert _generate(edited).config.candidate_hash != first
        protected = _generate(settings={**SETTINGS, "github_protection": "configured"})
        assert protected.config.candidate_hash != first


class TestWhatIsNotGenerated:
    def test_an_unsupported_stack_is_reported_with_no_files(self) -> None:
        generated = _generate(stack_id="react-spring-postgres")
        config = generated.config
        assert not config.stack.supported and config.files == [] and generated.layer == {}
        assert "nobody has validated" in config.stack.reason and not config.valid
        # In a reader's words: no requirement code, no catalogue key.
        assert "FR14" not in config.stack.reason
        assert "React with Spring Boot and PostgreSQL" in config.stack.reason

    def test_a_split_layout_has_no_template_yet_and_says_so(self) -> None:
        server = TRACKER["apps/api/src/server.ts"].replace("app.use(express.static(webDist));", "")
        config = _generate({**TRACKER, "apps/api/src/server.ts": server}).config
        assert not config.stack.supported
        assert config.stack.reason == (
            "the templates are written for the one-process layout, and this project is split"
        )

    def test_kubernetes_is_optional_and_generated_only_when_asked(self) -> None:
        skipped = _generate()
        assert skipped.config.kubernetes == "skipped"
        assert skipped.config.kubernetes_reason.startswith("optional, and not asked for")
        asked = _generate(settings={**SETTINGS, "kubernetes": True})
        assert asked.config.kubernetes == "generated"
        deployment = yaml.safe_load(asked.layer["k8s/deployment.yaml"])
        assert deployment["spec"]["template"]["spec"]["containers"][0]["image"] == (
            "sdlc-c4-task-tracker:v2"
        )


class TestTheCandidatesDependencies:
    def test_an_update_npm_could_not_apply_is_named_and_counted(self) -> None:
        generated = _generate(refuse={ROUTER.id})
        assert generated.notes["applied"] == [SUPERTEST.id]
        assert ROUTER.id in generated.notes["refused"]
        assert "1 of 2 included updates in the lockfile" in generated.summary

    def test_only_the_included_updates_are_asked_for(self) -> None:
        asked: list[str] = []

        def resolver(files, updates):
            asked.extend(u.id for u in updates)
            return Resolution(lockfile=files["package-lock.json"], resolved_by="scripted")

        generate(
            TRACKER,
            UPDATES,
            stack_id="mern",
            contract=CONTRACT,
            included=[SUPERTEST.id],
            settings=SETTINGS,
            version=2,
            code_version=3,
            now=NOW,
            resolver=resolver,
            validate=_no_linters,
        )
        assert asked == [SUPERTEST.id]


class TestTheTemplates:
    def test_every_template_loads_at_its_recorded_hash(self) -> None:
        assert len(render.track("mern")) == 9

    def test_a_template_edited_without_a_new_version_refuses_to_load(self, monkeypatch) -> None:
        original = render.Path.read_text

        def edited(self, *args, **kwargs):
            text = original(self, *args, **kwargs)
            return text + "# a quiet edit\n" if self.name == "Dockerfile.tmpl" else text

        monkeypatch.setattr(render.Path, "read_text", edited)
        with pytest.raises(render.TemplateChanged, match="edited without a new version"):
            render.load("mern/Dockerfile@2")

    def test_filling_is_strict_both_ways(self) -> None:
        template = render.load("mern/k8s-service.yaml@1")
        with pytest.raises(render.Unfilled, match="asks for port"):
            render.fill(template, {"service_name": "x"})
        with pytest.raises(render.Unfilled, match="values no template asks for: spare"):
            render.fill_all([template], {"service_name": "x", "port": "1", "spare": "y"})

    def test_marker_shaped_text_the_pattern_does_not_take_is_refused(self) -> None:
        """The first fill left `<<lockfile_sha256>>` in release.json: the marker
        pattern allowed no digits, so it was not a marker and went through as text."""
        odd = render.Template("odd@1", "a <<Not-A-Marker>> b", "0" * 64, "odd", "ignore")
        with pytest.raises(render.Unfilled, match="which is not a marker this fills"):
            render.fill(odd, {})

    def test_smoke_paths_come_from_the_client_and_the_contract_only_without_one(self) -> None:
        """The tracker's client declares one GET without a parameter. The graph
        fixture's contract names `/task-lists`, which this API does not answer: its
        page fallback would, with the app's HTML, so the client is read first."""
        assert smoke_paths(TRACKER, CONTRACT) == ["/tasks"]
        without = {p: t for p, t in TRACKER.items() if p != "packages/contract/src/client.ts"}
        assert smoke_paths(without, CONTRACT) == ["/task-lists"]


def test_an_update_npm_cannot_apply_in_time_is_refused_not_raised(monkeypatch) -> None:
    """A timeout applying one update refuses that update, as any npm failure does,
    rather than failing pipeline generation for every update."""
    import subprocess

    from c4.pipeline import candidate

    real = subprocess.run

    def slow(argv, **kwargs):
        if "install" in argv:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        return real(argv, **kwargs)

    monkeypatch.setattr(candidate.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(candidate.subprocess, "run", slow)
    monkeypatch.setattr(candidate, "npm_version", lambda: "npm 10.9.2")
    resolution = resolve(TRACKER, [SUPERTEST])
    assert resolution.applied == []
    assert (
        resolution.refused[SUPERTEST.id] == "npm could not apply it: it did not finish within 300 s"
    )


def test_the_candidate_resolves_with_the_cache_it_is_given(monkeypatch, tmp_path) -> None:
    """The baseline pin fills npm's cache and the candidate's resolution reads the
    same one, so applying an update finds most of the tree already there."""
    import subprocess

    from c4.pipeline import candidate

    seen: list[dict[str, str]] = []

    def npm(argv, **kwargs):
        seen.append(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(candidate.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(candidate.subprocess, "run", npm)
    monkeypatch.setattr(candidate, "npm_version", lambda: "npm 10.9.2")
    resolution = resolve(TRACKER, [SUPERTEST], cache=tmp_path / "npm")
    assert resolution.applied == [SUPERTEST.id]
    assert [env["npm_config_cache"] for env in seen] == [str(tmp_path / "npm")]


@pytest.mark.sandbox
class TestTheRealResolution:
    """npm itself, on the tracker's baseline pin, with no package downloaded or script run."""

    def test_an_update_is_applied_where_its_manifest_declares_it(self) -> None:
        resolution = resolve(TRACKER, [SUPERTEST])
        assert resolution.applied == [SUPERTEST.id] and resolution.refused == {}
        lock = json.loads(resolution.lockfile)
        assert lock["packages"]["node_modules/supertest"]["version"] == "7.3.0"
        assert set(resolution.manifests) == {"apps/api/package.json"}
        manifest = json.loads(resolution.manifests["apps/api/package.json"])
        assert manifest["devDependencies"]["supertest"] == "^7.3.0"

    def test_an_update_two_manifests_declare_is_applied_in_both(self) -> None:
        """Vitest is declared by both apps. Applied in one, the other would still
        ask for the old range, and the release would ship it half applied."""
        vitest = _update(
            "vitest", "2.1.9", "3.2.4", "apps/api/package.json", also=("apps/web/package.json",)
        )
        resolution = resolve(TRACKER, [vitest])
        assert resolution.applied == [vitest.id], resolution.refused
        assert set(resolution.manifests) == {"apps/api/package.json", "apps/web/package.json"}
        for path in resolution.manifests:
            assert json.loads(resolution.manifests[path])["devDependencies"]["vitest"] == "^3.2.4"

    def test_an_update_npm_cannot_apply_is_refused_and_the_rest_still_apply(self) -> None:
        missing = _update("supertest", "7.2.2", "99.0.0", "apps/api/package.json")
        resolution = resolve(TRACKER, [missing, ROUTER])
        assert set(resolution.refused) == {missing.id}
        assert resolution.refused[missing.id].startswith("npm could not apply it")
        assert resolution.applied == [ROUTER.id]
        lock = json.loads(resolution.lockfile)
        assert lock["packages"]["node_modules/supertest"]["version"] == "7.2.2"
