"""olcaBASIC: a BASIC-like language for openLCA."""

__version__ = "0.4.0"

from .engine import Engine  # noqa: E402
from .session import Session, RunResult  # noqa: E402

__all__ = ["Session", "RunResult", "Engine", "__version__"]
