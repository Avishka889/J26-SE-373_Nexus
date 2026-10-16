"""The trained arm: preparing what it learns from, and running it after.

Separated from the rest of the component because it is the one part whose work
happens elsewhere. The dataset preparation and the export run here, the GPU
hours run on Colab, and the trained weights come back to be served behind a
process boundary so that two gigabytes of wheels never enter the orchestrator.
"""

from .juliet import Example, assign_splits, evaluable, family_of, read_corpus

__all__ = ["Example", "assign_splits", "evaluable", "family_of", "read_corpus"]
