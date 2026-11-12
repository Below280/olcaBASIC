"""
Programme operator profiles.

EN 15804 sets the method; each programme operator adds its own rules.
Those rules live in a profile, chosen in the EPD block with PROGRAMME,
so another operator can be added as another module here without
touching the core EPD workflow.

    EPD "Concrete block"
      PROGRAMME "IES" GPI "5.1.0"
      ...
"""

from typing import Dict, Optional

from . import ies

PROFILES: Dict[str, object] = {
    "IES": ies.PROFILE,
}

ALIASES = {
    "INTERNATIONAL EPD SYSTEM": "IES",
    "ENVIRONDEC": "IES",
    "EPD INTERNATIONAL": "IES",
}


def get(name: str) -> Optional[object]:
    """The profile for a programme name, or None."""
    key = " ".join((name or "").upper().split())
    return PROFILES.get(ALIASES.get(key, key))


def names() -> list:
    return sorted(PROFILES)
