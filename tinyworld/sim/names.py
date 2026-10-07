"""Display names. Familiar mode shows the normal names. Alien mode shows made-up words."""
from __future__ import annotations

import numpy as np

from . import defs

_CONS = "bdfgklmnprstvz"
_VOWELS = "aeiou"
# No alien word may contain one of these.
_AVOID = sorted({w for n in defs.ALL_NAMES for w in n.split()} | {
    "air", "goal", "should", "try", "survive", "danger", "tip", "hint", "recipe",
})


def _word(rng: np.random.Generator) -> str:
    n = int(rng.integers(2, 4))
    w = "".join(_CONS[int(rng.integers(len(_CONS)))] + _VOWELS[int(rng.integers(len(_VOWELS)))] for _ in range(n))
    if rng.random() < 0.4:
        w += _CONS[int(rng.integers(len(_CONS)))]
    return w


def build_display_names(mode: str, seed: int) -> dict[str, str]:
    """Map every familiar name to the name the agent is shown."""
    if mode == "familiar":
        return {n: n for n in defs.ALL_NAMES}
    # A separate stream from the same seed, so terrain does not depend on the name mode.
    rng = np.random.default_rng([int(seed), 0xA11E])
    out: dict[str, str] = {}
    used: set[str] = set()
    for name in defs.ALL_NAMES:
        while True:
            w = _word(rng)
            if w not in used and not any(a in w for a in _AVOID):
                break
        used.add(w)
        out[name] = w
    return out
