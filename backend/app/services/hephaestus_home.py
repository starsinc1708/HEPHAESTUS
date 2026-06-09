"""Registry root resolution — single source for paths OUTSIDE any repo."""
from __future__ import annotations

import os
import pathlib


def hephaestus_home() -> pathlib.Path:
    """Return the HEPHAESTUS registry root: $HEPHAESTUS_HOME or ~/.hephaestus."""
    env = os.environ.get("HEPHAESTUS_HOME")
    if env:
        return pathlib.Path(env)
    return pathlib.Path.home() / ".hephaestus"