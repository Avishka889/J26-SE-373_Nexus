"""Validated templates, each pinned by its hash, and the one way they are filled.

A template is a file under `templates/`, named in `MANIFEST.json` with the
sha256 of its text, the path it renders to and what the file is for. Loading one
checks the hash, so a template edited without a new version refuses to load, and
every generated file records the id and version of the template it came from.
A template version is what was validated: a change to the text is a new version.

Values go in at `<<name>>` markers, and filling is strict: a marker with no
value, or a value no template of the track asks for, is an error rather than a
file with a hole in it. The markers were chosen because nothing in a Dockerfile,
a GitHub workflow (`${{ }}`) or JSON writes them. Values are checked for their
shape where they are made, before they reach a template, so that nothing a
project supplies can break out of the YAML, JSON or shell it lands in.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent / "templates"

_MARK = re.compile(r"<<([a-z][a-z0-9_]*)>>")
#: Anything shaped like a marker that the marker pattern did not take.
_RESIDUE = re.compile(r"<<[^<>\s]*>>")


class TemplateChanged(RuntimeError):
    """A template's text no longer matches the hash its manifest records."""


class Unfilled(ValueError):
    """A template asked for a value that was not given, or a value went unused."""


@dataclass(frozen=True)
class Template:
    #: The template and its version, `mern/deploy.yml@1`.
    id: str
    text: str
    sha256: str
    #: Where it renders to, which may itself hold markers.
    path: str
    purpose: str

    def markers(self) -> set[str]:
        return set(_MARK.findall(self.text)) | set(_MARK.findall(self.path))


def manifest() -> dict[str, dict[str, str]]:
    return json.loads((HERE / "MANIFEST.json").read_text(encoding="utf-8"))


def load(template_id: str) -> Template:
    entry = manifest()[template_id]
    text = (HERE / entry["file"]).read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != entry["sha256"]:
        raise TemplateChanged(
            f"{template_id} was edited without a new version: the text hashes to "
            f"{digest[:12]}, the manifest says {entry['sha256'][:12]}. A changed template is "
            "a new version: bump it in its id and record the new hash."
        )
    return Template(template_id, text, digest, entry["path"], entry["purpose"])


def track(stack: str) -> list[Template]:
    """Every template of one stack, in the manifest's order."""
    return [load(template_id) for template_id in manifest() if template_id.startswith(f"{stack}/")]


def _substitute(text: str, values: dict[str, str], template_id: str) -> str:
    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise Unfilled(f"{template_id} asks for {name}, and no value was given")
        return values[name]

    left = _RESIDUE.search(_MARK.sub("", text))
    if left:
        raise Unfilled(f"{template_id} holds {left.group(0)}, which is not a marker this fills")
    return _MARK.sub(value, text)


def fill(template: Template, values: dict[str, str]) -> tuple[str, str]:
    """The path and the text of one filled template; its own id is always a value."""
    given = {**values, "template_id": template.id}
    return (
        _substitute(template.path, given, template.id),
        _substitute(template.text, given, template.id),
    )


def fill_all(templates: list[Template], values: dict[str, str]) -> dict[str, tuple[Template, str]]:
    """Every template filled, by the path it renders to, with no value left over."""
    asked = set().union(*(template.markers() for template in templates)) if templates else set()
    unused = sorted(set(values) - asked)
    if unused:
        raise Unfilled(f"values no template asks for: {', '.join(unused)}")
    filled: dict[str, tuple[Template, str]] = {}
    for template in templates:
        path, text = fill(template, values)
        filled[path] = (template, text)
    return filled
