"""The layout a pipeline is chosen by, read from the platform's own generated project.

The task tracker in `studies/clients/` is a real C2 project. Each variant below
changes one fact in it, and the layout must move with that fact and say so in
its evidence; a detection that answered from the stack's name would not move.
"""

from pathlib import Path

import pytest
from c4.eval.loaders.clients import read_client
from c4.pipeline.layout import STRIP_TYPES_NODE, Undetectable, detect

TRACKER = read_client(Path(__file__).parents[1] / "studies" / "clients" / "task-tracker")
SERVER = "apps/api/src/server.ts"


def _with(changed: dict[str, str]) -> dict[str, str]:
    return {**TRACKER, **changed}


class TestTheGeneratedProject:
    def test_the_task_tracker_is_one_process_and_says_why(self) -> None:
        found = detect(TRACKER)
        layout = found.layout
        assert (layout.kind, layout.frontend_dir, layout.backend_dir) == (
            "one-process",
            "apps/web",
            "apps/api",
        )
        assert layout.shared_dirs == ["packages/contract"]
        assert layout.serves_frontend_from_backend
        assert found.frontend_output == "apps/web/dist"
        assert any("serves apps/web/dist with express.static" in line for line in layout.evidence)

    def test_the_runtime_is_read_from_the_start_script_and_the_entry(self) -> None:
        runtime = detect(TRACKER).runtime
        assert runtime is not None
        assert runtime.entry == SERVER
        assert runtime.node_minimum == STRIP_TYPES_NODE == "22.6"
        assert runtime.port == 3001


class TestEachFactMovesTheLayout:
    def test_a_backend_that_serves_nothing_is_split(self) -> None:
        quiet = TRACKER[SERVER].replace("app.use(express.static(webDist));", "")
        found = detect(_with({SERVER: quiet}))
        assert found.layout.kind == "split"
        assert not found.layout.serves_frontend_from_backend

    def test_serving_a_directory_the_frontend_does_not_build_to_is_split(self) -> None:
        """express.static is there, but the frontend now builds somewhere else."""
        config = TRACKER["apps/web/vite.config.ts"].replace(
            "plugins: [react(), tailwindcss()],",
            'plugins: [react(), tailwindcss()],\n  build: { outDir: "public-build" },',
        )
        found = detect(_with({"apps/web/vite.config.ts": config}))
        assert found.frontend_output == "apps/web/public-build"
        assert found.layout.kind == "split"
        assert (
            "apps/web/vite.config.ts sets the build output to public-build" in found.layout.evidence
        )

    def test_a_backend_run_as_javascript_needs_no_particular_node(self) -> None:
        manifest = TRACKER["apps/api/package.json"].replace(
            '"start": "node --experimental-strip-types src/server.ts"',
            '"start": "node src/server.ts"',
        )
        runtime = detect(_with({"apps/api/package.json": manifest})).runtime
        assert runtime is not None and runtime.node_minimum is None

    def test_without_a_frontend_it_is_backend_only(self) -> None:
        files = {path: text for path, text in TRACKER.items() if not path.startswith("apps/web/")}
        assert detect(files).layout.kind == "backend-only"


class TestWhatCannotBeRead:
    def test_no_root_manifest(self) -> None:
        files = {path: text for path, text in TRACKER.items() if path != "package.json"}
        with pytest.raises(Undetectable, match=r"no package\.json at the root"):
            detect(files)

    def test_a_start_script_that_names_no_file(self) -> None:
        manifest = TRACKER["apps/api/package.json"].replace(
            '"start": "node --experimental-strip-types src/server.ts"', '"start": "tsx watch"'
        )
        with pytest.raises(Undetectable, match="names no file for node to run"):
            detect(_with({"apps/api/package.json": manifest}))

    def test_an_entry_the_project_does_not_have(self) -> None:
        files = {path: text for path, text in TRACKER.items() if path != SERVER}
        with pytest.raises(Undetectable, match="which is not in the project"):
            detect(files)
