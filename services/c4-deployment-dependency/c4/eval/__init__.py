"""The study: the hybrid against the SemVer rule alone, on cases whose outcome was observed.

Rules this package holds to, each learned the hard way by C3's study:

- **Ground truth is what happened**, stored raw, with the level derived by a
  versioned rubric, so a rubric change never forces relabelling.
- **Epochs are never pooled.** One table per epoch, headed by its commit, its
  corpus hash, its model, its rules, its rubric and its split.
- **Every arm is computed from recorded votes**, on identical cases, and a
  degenerate arm is marked where it appears, so a perfect recall from calling
  everything High is never read as a result.
- **The held out set is read once**, deliberately, and every read is recorded.
"""
