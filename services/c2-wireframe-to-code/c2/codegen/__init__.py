"""Code generation: templates and rules for structure, an optional model fill."""

from .manifest import FileSet, GeneratedFile
from .monorepo import generate_monorepo

__all__ = ["FileSet", "GeneratedFile", "generate_monorepo"]
