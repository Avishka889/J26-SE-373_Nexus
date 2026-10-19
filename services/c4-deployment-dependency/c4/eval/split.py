"""Which cases are held out, decided once, by a hash of the update.

About one case in five is held out for the final evaluation (proposal 3.5.2),
and the choice is a function of the update's key alone: the ecosystem, the
package and the two versions. So the same update seen through two different
clients is always on the same side, adding cases never moves an existing one
across, and nobody can choose which cases are held out after seeing a result.
The seed is fixed and dated in the string itself.
"""

import hashlib

SEED = "c4-heldout-2026-09-27"

#: Out of 100.
HELD_OUT_SHARE = 20


def held_out(update_key: str) -> bool:
    digest = hashlib.sha256(f"{SEED}:{update_key}".encode()).hexdigest()
    return int(digest[:8], 16) % 100 < HELD_OUT_SHARE
