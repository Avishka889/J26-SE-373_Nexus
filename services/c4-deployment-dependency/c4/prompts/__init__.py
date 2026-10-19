"""The prompts C4 sends, each pinned by its hash (NFR13).

A prompt is a file here, named in `MANIFEST.json` with the sha256 of its text.
Loading one checks the hash, so a prompt edited without its manifest entry
refuses to load, and every model call records the id and hash it was made with.
Two studies that disagree can then be told apart by prompt as well as by model,
which is the half of reproducibility the model string alone does not give.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent


class PromptChanged(RuntimeError):
    """A prompt's text no longer matches the hash its manifest records."""


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str
    sha256: str


def manifest() -> dict[str, dict[str, str]]:
    return json.loads((HERE / "MANIFEST.json").read_text(encoding="utf-8"))


def load(prompt_id: str) -> Prompt:
    entry = manifest()[prompt_id]
    text = (HERE / entry["file"]).read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != entry["sha256"]:
        raise PromptChanged(
            f"{prompt_id} was edited without its manifest entry: the text hashes to "
            f"{digest[:12]}, the manifest says {entry['sha256'][:12]}. A changed prompt is a "
            "new prompt: give it a new id and a new file, and record it."
        )
    return Prompt(prompt_id, text, digest)
