"""Reading what a project declares, on the manifests this platform actually produces.

The npm case is the layout C2 generates, copied here as C2 wrote it on
2026-09-27 rather than imported, because this component's tests must stand on
their own when the component is placed in its own repository. The Maven case is
C3's checked in Java sample, a real POM with a bill of materials, a managed
version and plugins.
"""

import json
from pathlib import Path

from c4.intake.manifests import declared_dependencies, maven_dependencies, npm_dependencies

ROOT_PACKAGE = """{
  "name": "generated-app",
  "private": true,
  "type": "module",
  "workspaces": ["apps/*", "packages/*"],
  "scripts": {
    "build": "npm run build --workspace @app/web",
    "start": "npm run start --workspace @app/api"
  }
}
"""

API_PACKAGE = """{
  "name": "@app/api",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "start": "node --experimental-strip-types src/server.ts"
  },
  "dependencies": {
    "@app/contract": "*",
    "express": "^5.1.0"
  },
  "devDependencies": {
    "@types/express": "^5.0.0",
    "@types/supertest": "^6.0.0",
    "supertest": "^7.0.0",
    "typescript": "^5.7.0",
    "vitest": "^2.1.0"
  }
}
"""

SAMPLE_POM = (
    Path(__file__).resolve().parents[2]
    / "c3-testing-security"
    / "fixtures"
    / "java-sample"
    / "pom.xml"
)


def _monorepo() -> dict[str, str]:
    files = {"package.json": ROOT_PACKAGE}
    files["apps/api/package.json"] = API_PACKAGE
    files["apps/web/package.json"] = json.dumps(
        {
            "name": "@app/web",
            "dependencies": {"@app/contract": "*", "react": "^19.0.0"},
            "devDependencies": {"vite": "^6.0.0"},
        },
        indent=2,
    )
    files["packages/contract/package.json"] = json.dumps({"name": "@app/contract"}, indent=2)
    # Not a workspace, and must not be read as one.
    files["node_modules/express/package.json"] = json.dumps({"name": "express"})
    return files


def _by_name(found, package, manifest):
    return next(d for d in found if d.package == package and d.manifest_path == manifest)


class TestTheGeneratedMonorepo:
    def test_every_workspace_is_read_and_nothing_else(self) -> None:
        found = npm_dependencies(_monorepo())
        assert {d.manifest_path for d in found} == {
            "apps/api/package.json",
            "apps/web/package.json",
        }

    def test_sections_keep_their_scope_and_line(self) -> None:
        files = _monorepo()
        found = npm_dependencies(files)
        express = _by_name(found, "express", "apps/api/package.json")
        vitest = _by_name(found, "vitest", "apps/api/package.json")
        assert (express.scope, express.declared, express.not_registry) == ("prod", "^5.1.0", "")
        assert vitest.scope == "dev"
        line = files["apps/api/package.json"].splitlines()[express.line - 1]
        assert '"express"' in line

    def test_the_workspace_contract_package_is_not_a_registry_dependency(self) -> None:
        """Asking the registry about `@app/contract` would find nothing, or an
        unrelated public package of the same name."""
        found = npm_dependencies(_monorepo())
        contract = _by_name(found, "@app/contract", "apps/api/package.json")
        assert "package in this repository" in contract.not_registry


class TestRangesThatLeaveTheRegistry:
    def test_each_is_marked_with_why(self) -> None:
        files = {
            "package.json": json.dumps(
                {
                    "dependencies": {
                        "local": "file:../local",
                        "ws": "workspace:^1.0.0",
                        "forked": "git+https://github.com/someone/forked.git",
                        "tarball": "https://example.com/x.tgz",
                        "renamed": "npm:lodash@^4.17.0",
                        "plain": "^1.0.0",
                    }
                }
            )
        }
        marked = {d.package: d.not_registry for d in npm_dependencies(files)}
        assert all(marked[name] for name in ("local", "ws", "forked", "tarball", "renamed"))
        assert marked["plain"] == ""


class TestTheJavaSample:
    def test_a_bill_of_materials_resolves_its_version_from_the_properties(self) -> None:
        found = maven_dependencies({"pom.xml": SAMPLE_POM.read_text()})
        bom = next(d for d in found if d.package == "org.junit:junit-bom")
        assert bom.scope == "import"
        assert bom.declared and "${" not in bom.declared
        assert bom.not_registry == ""

    def test_a_managed_version_is_not_guessed(self) -> None:
        found = maven_dependencies({"pom.xml": SAMPLE_POM.read_text()})
        jupiter = next(d for d in found if d.package == "org.junit.jupiter:junit-jupiter")
        assert jupiter.scope == "test"
        assert "managed by a parent or a bill of materials" in jupiter.not_registry

    def test_plugins_are_dependencies_a_build_runs(self) -> None:
        found = maven_dependencies({"pom.xml": SAMPLE_POM.read_text()})
        compiler = next(
            d for d in found if d.package == "org.apache.maven.plugins:maven-compiler-plugin"
        )
        assert (compiler.scope, compiler.declared) == ("plugin", "3.15.0")
        assert compiler.line is not None

    def test_an_undefined_property_is_said_rather_than_sent(self) -> None:
        pom = SAMPLE_POM.read_text().replace("${junit.version}", "${nowhere.version}")
        bom = next(
            d for d in maven_dependencies({"pom.xml": pom}) if d.package == "org.junit:junit-bom"
        )
        assert "which this POM does not define" in bom.not_registry


def test_both_ecosystems_are_read_together() -> None:
    files = {**_monorepo(), "pom.xml": SAMPLE_POM.read_text()}
    ecosystems = {d.ecosystem for d in declared_dependencies(files)}
    assert ecosystems == {"npm", "maven"}
