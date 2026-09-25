"""Running the fill: one file at a time, checked, kept or put back.

The fill itself is in `fill.py` and is pure. This is the part that touches a
repository: it writes the model's answer into the workspace, asks the runner
whether the tests it claimed to write are really there, and puts the skeleton
back when they are not.

**Collected, not run.** The check is `vitest list`, which parses the file and
reports the tests it finds without executing any of them. That is exactly what
the fill is responsible for: the file compiles, and the tests it was asked to
write exist under the names it was given. Whether they pass is a result, and
results belong to the stage that runs them. Running here would also make the
generation stage's report, whose every case is `not-run`, true only because
nobody had looked.

**A test that fails later is a finding, not a fill failure.** A criterion test
that turns red says the application does not do what the sprint said done
means. That is the report doing its job, and it is a different thing from the
API oracle's third tier, where no test could pass because the feature does not
exist at all: there the absence is asserted as a gap, here the behaviour is
asserted as a test and the answer is measured.
"""

import json
import logging
import posixpath
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from pydantic_ai import Agent
from sdlc_contracts import ApiContract, SprintPlan, UserStory

from ..harness import Sandbox, TargetRepo
from ..harness import node_lane as lane
from .criteria import SUPERTEST_IMPORT, fresh_app_block, fresh_app_of
from .decisions import WRITE_AGAIN_FOR, answered
from .fill import (
    FillContext,
    FilledFile,
    declarations_of,
    declared_names,
    fill,
    skipped_names,
    type_only_names,
    written_names,
)

log = logging.getLogger(__name__)

#: What counts as an export a test may call. A regex rather than a parser
#: because the answer feeds a prompt: an export this misses is a module the
#: model is not told about, which costs a fill, not a wrong number.
_EXPORTS = re.compile(
    r"^export\s+(?:async\s+)?(?:function|const|let|class|interface|type)\s+(\w+)"
    r"|^export\s*\{([^}]*)\}",
    re.MULTILINE,
)


@dataclass
class FillResult:
    """What happened to one file, in enough detail to explain it."""

    path: str
    accepted: bool
    attempts: int
    reasons: list[str] = field(default_factory=list)
    #: The names the fill wrote a body for, when it was accepted.
    filled: list[str] = field(default_factory=list)
    #: The names it left declared, which stay skeletons and stay honest.
    left_declared: list[str] = field(default_factory=list)


def exports_of(source: str) -> list[str]:
    names: list[str] = []
    for direct, grouped in _EXPORTS.findall(source):
        if direct:
            names.append(direct)
        for part in grouped.split(","):
            cleaned = part.strip().split(" as ")[-1].strip()
            if cleaned and cleaned != "default":
                names.append(cleaned)
    return sorted(set(names))


def fresh_bindings(repo: TargetRepo) -> dict[str, list[str]]:
    """Per side, the values its `src/app.ts` exports: what a criteria test's
    setup loads afresh before every test (`criteria.fresh_app_block`).

    Types are left out. `typeof import(...)` has no member for a name that
    exists only at compile time, so binding one would not compile.
    """
    found: dict[str, list[str]] = {}
    for app in repo.apps:
        path = f"{app}/src/app.ts"
        text = repo.read(path)
        if text is None:
            continue
        types = type_only_names({path: text})
        names = [name for name in exports_of(text) if name not in types]
        if names:
            found[app.removeprefix("apps/")] = names
    return found


def modules_for(repo: TargetRepo, *, limit: int = 12, from_test: str = "") -> dict[str, list[str]]:
    """The app's own source files and what they export.

    Test files and generated test directories are left out: a model told about
    the other tests writes tests about the tests. Capped, because this goes
    into a prompt and a large repository would fill the context with modules
    the criterion has nothing to do with.

    **Keyed by the specifier the test has to write, not by the repository path.**
    `from_test` is where the test file lives, so `apps/api/src/app.ts` is offered
    to a test in `apps/api/src/__tests__/` as `../app.ts`, which is what the
    rules' own oracle writes and what vitest can resolve.

    It was the repository path until 2026-09-26, and the model did exactly as it
    was told: the first live fill on generated code wrote
    `import { app } from "apps/api/src/app.ts"`, the runner could not load it,
    and the whole file was refused for not collecting. Two of five stories lost
    every attempt that way, and the refusal reason named the import rather than
    the prompt, so it read as the model's mistake.
    """
    found: dict[str, list[str]] = {}
    for module, text in _app_sources(repo, from_test):
        exports = exports_of(text)
        if exports:
            found[module] = exports
        if len(found) >= limit:
            break
    return found


#: How much of the prompt the declarations may take, in characters. A generated
#: app's come to a few hundred; a large repository's would crowd the criterion
#: out, which is what the module list's own cap is for.
DECLARATIONS_BUDGET = 4000


def declarations_for(
    repo: TargetRepo, *, from_test: str = "", limit: int = 12, budget: int = DECLARATIONS_BUDGET
) -> dict[str, list[str]]:
    """What the app's own modules declare (`declarations_of`), keyed as the test
    imports them, from the same files `modules_for` offers."""
    found: dict[str, list[str]] = {}
    spent = 0
    for module, text in _app_sources(repo, from_test):
        declared: list[str] = []
        for one in declarations_of(text):
            if spent + len(one) > budget:
                break
            declared.append(one)
            spent += len(one)
        if declared:
            found[module] = declared
        if len(found) >= limit:
            break
    return found


def _app_sources(repo: TargetRepo, from_test: str) -> Iterator[tuple[str, str]]:
    """The app's own source files, test files left out, each with its specifier."""
    source = repo.app_path / "src"
    if not source.is_dir():
        return
    for path in sorted(source.rglob("*.ts")):
        if "__tests__" in path.parts or path.name.endswith((".test.ts", ".spec.ts")):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        yield specifier(repo.relative(path), from_test), text


def specifier(module: str, from_test: str) -> str:
    """How a test at `from_test` imports the module at `module`.

    Relative, and with the extension kept: the generated project sets
    `allowImportingTsExtensions` and every import the code generator writes
    carries `.ts`, so dropping it here would offer the model a specifier that
    half the repository disagrees with.

    With no test path to measure from, the repository path is returned unchanged.
    That is the old behaviour and it is wrong for importing, so it is only what
    a caller that asked no question gets.
    """
    if not from_test:
        return module
    relative = posixpath.relpath(module, posixpath.dirname(from_test))
    return relative if relative.startswith(".") else f"./{relative}"


def endpoints_for(contract: ApiContract, story: UserStory) -> list[str]:
    """The endpoints that exist for this story, as one line each."""
    return [
        f"{endpoint.method} {endpoint.path}"
        + (f" ({endpoint.summary})" if endpoint.summary else "")
        for endpoint in contract.endpoints
        if story.id in endpoint.traces.story_ids
    ]


def context_for(
    story: UserStory,
    contract: ApiContract,
    repo: TargetRepo,
    *,
    path: str = "",
    skeleton: str = "",
) -> FillContext:
    """What the model is told, for the one file it is about to write.

    `path` is that file. It is what makes the module list importable rather
    than merely true. `skeleton` is what the model is handed: a module its setup
    loads afresh is offered as names already bound, and not as a module to
    import, because importing it again is exactly the sharing the setup ends.
    """
    modules = modules_for(repo, from_test=path)
    bound: dict[str, list[str]] = {}
    fresh = fresh_app_of(skeleton)
    if fresh is not None:
        module, names = fresh
        modules.pop(module, None)
        bound = {module: names}
    return FillContext(
        story_title=story.title,
        criteria=[
            f"given {criterion.given}, when {criterion.when}, then {criterion.then}"
            for criterion in story.acceptance
        ],
        modules=modules,
        endpoints=endpoints_for(contract, story),
        bound=bound,
        declarations=declarations_for(repo, from_test=path),
    )


def _story_of(path: str, sprint: SprintPlan) -> UserStory | None:
    name = path.rsplit("/", 1)[-1].removesuffix(".criteria.test.ts")
    for story in sprint.proposed:
        if story.id == name or story.id.replace("/", "-") == name:
            return story
    return None


def _project_sources(repo: TargetRepo, files: dict[str, str]) -> dict[str, str]:
    """Every TypeScript source the project has, test files excluded.

    The generated files are read from the map rather than from disk, because
    the ones this pass is about may not be written yet.
    """
    sources = {
        path: content
        for path, content in files.items()
        if path.endswith(".ts") and "__tests__" not in path
    }
    for found in repo.root.rglob("*.ts"):
        if "node_modules" in found.parts or "__tests__" in found.parts:
            continue
        path = found.relative_to(repo.root).as_posix()
        if path not in sources:
            content = repo.read(path)
            if content is not None:
                sources[path] = content
    return sources


@dataclass(frozen=True)
class Merged:
    """One criteria file that already had tests, and what it should hold now."""

    path: str
    content: str
    #: Written before this run and not to be touched by it.
    carried: tuple[str, ...]
    #: Criteria this story has now that nothing tests yet.
    declared: tuple[str, ...]
    #: Moved onto the setup that loads the app afresh before every test.
    moved: bool = False
    #: Why a file whose tests share one app could not be moved, when it could not.
    left_shared: str = ""


def merge_carried(repo: TargetRepo, files: dict[str, str]) -> dict[str, Merged]:
    """Keep the tests a criteria file already has, and declare what it lacks.

    **The generator is the one thing that may not change a test silently.** A
    criteria test encodes the behaviour a model observed when it was written,
    so when the behaviour moves underneath it the test goes stale, fails, and
    the healing loop rewrites it under the guard: a mutant has to die, the
    unchanged production code has to pass, and a refusal is recorded. A
    generator that overwrites it first does that same job with none of those
    checks, and the failure the whole component exists to classify never
    happens.

    **It used to carry only when the criteria were textually identical, and
    that never happened.** A design regeneration rewrites every criterion:
    measured on the task tracker, "given a user whose list holds the task
    \"Buy milk\", when they open that task, then the title is shown to them"
    came back as "given the list showing the task \"Buy milk\", when I open
    that task, then the task's name is displayed". Same criterion, rewritten
    down to the person. So every file was regenerated, every test written
    against the old behaviour was thrown away by the one component forbidden to
    do that, and no stale test could exist on generated code at all. The
    headline contribution had no input.

    So a file with bodies keeps them, and gains an `it.todo` for each criterion
    the story now has that nothing already covers. The file grows once per
    regeneration, and that is the honest shape: a reworded criterion is a new
    criterion, which is what the exact matching in `sdlc_contracts.identity`
    established, so the platform cannot claim the old test and the new criterion
    are about the same thing. Both are declared, and the report counts what the
    file holds.

    Oracle tests are not carried and are not meant to be: they assert what the
    contract declares, so they should follow the contract on every run.

    **A carried file is moved onto the fresh app setup when it lacks it.** Tests
    written before the setup existed import the app once for the whole file, so
    each one's "given" includes what the tests before it left. Only the import
    changes (`with_fresh_app`): every body keeps every character, because the
    setup binds each export under the name the test already uses.

    **And it gains the HTTP client the skeleton imports, when it has none**
    (`with_client`). The todos added to it are written against its imports, and
    a file carried from before the skeleton imported supertest gave a fill
    nothing to call the API with, which is how Movie Tracker's criteria stayed
    todos.
    """
    merged: dict[str, Merged] = {}
    for path, skeleton in files.items():
        if not path.endswith(".criteria.test.ts"):
            continue
        existing = repo.read(path)
        if existing is None:
            continue
        carried = written_names(existing)
        # A quarantined test stays as it is, skipped with its reason above it,
        # until a person restores it (`decisions.py`): it is not missing, so it
        # is never declared again, and a fill never writes over it.
        set_aside = skipped_names(existing)
        if not carried and not set_aside and WRITE_AGAIN_FOR not in existing:
            # Nothing was ever written here, so there is nothing to protect and
            # a fresh skeleton is both cheaper and more accurate. A test sent
            # back to be written again is a todo now, and its file is kept for
            # the reason above it, which is what the fill is to answer.
            continue
        have = set(carried) | set(set_aside) | set(declared_names(existing))
        missing = [one for one in declared_names(skeleton) if one not in have]
        content = _with_todos(existing, missing)
        moved, left_shared = False, ""
        fresh = fresh_app_of(skeleton)
        if fresh is not None and fresh_app_of(content) is None:
            content, left_shared = with_fresh_app(content, *fresh)
            moved = fresh_app_of(content) is not None
        if SUPERTEST_IMPORT in skeleton and _CLIENT_IMPORT.search(content) is None:
            content = with_client(content)
        merged[path] = Merged(
            path=path,
            content=content,
            # A quarantined test is a case too: the report declares it, and the
            # run reports it skipped.
            carried=tuple(carried) + tuple(set_aside),
            declared=tuple(declared_names(existing)) + tuple(missing),
            moved=moved,
            left_shared=left_shared,
        )
    return merged


#: A static import, one statement, across lines when it is braced over several.
_STATIC_IMPORT = re.compile(
    r"^import\s+(?P<clause>[^;]*?)\s+from\s*[\"'](?P<from>[^\"']+)[\"'][ \t]*;?[ \t]*\n?",
    re.MULTILINE,
)

#: Any import statement, to find where the imports end.
_ANY_IMPORT = re.compile(r"^import\b[\s\S]*?[\"'][^\"']+[\"'][ \t]*;?[ \t]*$", re.MULTILINE)

_VITEST_IMPORT = re.compile(r"import\s*\{(?P<names>[^}]*)\}\s*from\s*[\"']vitest[\"']")


def with_fresh_app(source: str, module: str, names: Sequence[str]) -> tuple[str, str]:
    """A test file moved onto the setup that loads `module` afresh per test.

    The file's value imports from `module` go, the setup binding every one of
    `names` comes in after the imports, and vitest's import gains the two names
    the setup calls. Nothing else changes. Returns the file and, when it could
    not be moved, why; a file that never imports `module` shares nothing and
    comes back as it was, with no reason.
    """
    found = [
        match
        for match in _STATIC_IMPORT.finditer(source)
        if match.group("from") == module and not match.group("clause").startswith("type ")
    ]
    if not found:
        return source, ""
    types: list[str] = []
    for match in found:
        clause = match.group("clause").strip()
        if not (clause.startswith("{") and clause.endswith("}")):
            return source, (
                f"it imports {module} as a whole ({clause}), so its names cannot be bound "
                "one by one"
            )
        for part in (one.strip() for one in clause[1:-1].split(",")):
            if not part:
                continue
            if part.startswith("type "):
                types.append(part.removeprefix("type ").strip())
                continue
            if " as " in part:
                return source, (
                    f"it renames {part} on import, and the setup binds each export under "
                    "its own name"
                )
            if part not in names:
                return source, f"it imports {part}, which {module} does not export as a value"
    if _VITEST_IMPORT.search(source) is None:
        return source, "it has no braced vitest import to add the setup's two names to"

    kept = f'import type {{ {", ".join(types)} }} from "{module}";\n' if types else ""
    for index, match in enumerate(reversed(found)):
        # The last import found keeps the file's type imports, if it had any.
        replacement = kept if index == len(found) - 1 else ""
        source = source[: match.start()] + replacement + source[match.end() :]

    vitest = _VITEST_IMPORT.search(source)
    assert vitest is not None
    have = [one.strip() for one in vitest.group("names").split(",") if one.strip()]
    wanted = have + [one for one in ("beforeEach", "vi") if one not in have]
    source = (
        source[: vitest.start("names")]
        + " "
        + ", ".join(wanted)
        + " "
        + source[vitest.end("names") :]
    )

    ends = [match.end() for match in _ANY_IMPORT.finditer(source)]
    end = ends[-1] if ends else 0
    return source[:end] + "\n\n" + fresh_app_block(names, module).rstrip("\n") + source[end:], ""


#: The client's import however a file spells it: `request` or another name.
_CLIENT_IMPORT = re.compile(r"^import\s+\w+\s+from\s*[\"']supertest[\"']", re.MULTILINE)


def with_client(source: str) -> str:
    """The file with the skeleton's HTTP client imported after vitest's import.

    A file with no braced vitest import comes back as it was: there is no line
    this generator wrote to put it after.
    """
    vitest = _VITEST_IMPORT.search(source)
    if vitest is None:
        return source
    end = source.find("\n", vitest.end())
    end = len(source) if end == -1 else end + 1
    return source[:end] + SUPERTEST_IMPORT + "\n" + source[end:]


def _with_todos(existing: str, names: list[str]) -> str:
    """The file with a todo added for each criterion nothing covers yet.

    Inserted before the last closing brace, which is where the `describe` this
    generator writes ends. A file whose shape this cannot find keeps its tests
    and gains nothing, because appending after the end would be a syntax error
    and a file that will not parse is worse than a criterion without a test.
    """
    if not names:
        return existing
    closing = existing.rstrip().rfind("});")
    if closing == -1:
        return existing
    added = "".join(f"  it.todo({json.dumps(one)});\n" for one in names)
    return existing[:closing] + added + existing[closing:]


async def fill_criteria(
    agent: Agent[None, FilledFile],
    repo: TargetRepo,
    sandbox: Sandbox,
    *,
    files: dict[str, str],
    sprint: SprintPlan,
    contract: ApiContract,
) -> list[FillResult]:
    """Every criteria file, filled and checked, in the workspace.

    The workspace is expected to hold the rest of the generated project and its
    install already: the check runs the real collector, which needs the real
    modules the test imports.
    """
    results: list[FillResult] = []
    # Read once for the whole pass: the project's own source is what says
    # whether a name the model constructs exists at run time.
    types_only = type_only_names(_project_sources(repo, files))
    for path in sorted(files):
        if not path.endswith(".criteria.test.ts"):
            continue
        if not declared_names(files[path]):
            # Every criterion in this file already has a body, so there is
            # nothing to write and nothing to risk by asking.
            continue
        skeleton = files[path]
        story = _story_of(path, sprint)
        if story is None:
            results.append(
                FillResult(
                    path=path,
                    accepted=False,
                    attempts=0,
                    reasons=["no story in this sprint matches the file name"],
                    left_declared=declared_names(skeleton),
                )
            )
            continue

        context = context_for(story, contract, repo, path=path, skeleton=skeleton)
        context.types_only = sorted(types_only)

        def collects(content: str, path: str = path, skeleton: str = skeleton) -> list[str]:
            """Whether the runner can see the tests this draft claims to have.

            Written to disk because that is the only way to ask, and put back
            on the way out of every failed attempt: a file the runner cannot
            collect is not a test file whatever it looks like, and leaving it
            there would put cases in the report that no runner will ever
            report on.

            The reason names what the runner said about **this** file. It used
            to carry the tail of whichever app happened to be collected last,
            which in a two app repository is a different app's output, naming
            other files' tests.

            The compiler is asked first, because it is the cheaper question and
            the more useful answer. Vitest strips types, so a draft that calls a
            method the module does not have parses, collects, runs, and fails at
            run time reading as the application's fault: `app.request(...)` on an
            Express app cost this component six repairs and a whole healing run
            before anybody asked `tsc`. It is also what the fill discipline has
            always said and never done.
            """
            repo.write(path, content)
            _, problems = lane.typecheck(repo, sandbox, path)
            if problems:
                repo.write(path, skeleton)
                return [
                    "the compiler refused this file: "
                    + "; ".join(problems[:4])
                    + ". Vitest strips types, so this would have run and failed "
                    "looking like the application's fault"
                ]
            _, listed = lane.collect(repo, sandbox)
            collected = {name for file_path, name in listed if file_path == path}
            wanted = written_names(content)
            missing = [name for name in wanted if not any(name in seen for seen in collected)]
            if not missing:
                return []
            # Asked before the skeleton goes back, or the runner is being asked
            # about a file of todos and answers `[]` about every draft alike.
            step = lane.collect_one(repo, sandbox, path)
            repo.write(path, skeleton)
            return [
                f"the runner did not collect {len(missing)} of the {len(wanted)} tests you "
                f'wrote, starting with "{missing[0]}". A file it cannot parse contributes '
                f"no tests at all. It said: {step.tail[-400:]}"
            ]

        outcome = await fill(
            agent,
            skeleton=skeleton,
            context=context,
            types_only=types_only,
            verify=collects,
        )
        if not outcome.accepted or outcome.content is None:
            repo.write(path, skeleton)
            results.append(
                FillResult(
                    path=path,
                    accepted=False,
                    attempts=outcome.attempts,
                    reasons=list(outcome.refused_reasons),
                    left_declared=declared_names(skeleton),
                )
            )
            continue

        # A request to write a test again is answered once the test is written.
        content = answered(outcome.content)
        if content != outcome.content:
            repo.write(path, content)
        files[path] = content
        results.append(
            FillResult(
                path=path,
                accepted=True,
                attempts=outcome.attempts,
                filled=written_names(content),
                left_declared=declared_names(content),
            )
        )
    return results
