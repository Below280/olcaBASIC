"""
Templates that ship with olcaBASIC.

    NEW FROM TEMPLATE "epd_skeleton" AS "my_epd.baslca"

copies one into the working folder. A template is an ordinary .baslca
program with comments where a decision has to be made.
"""

from importlib import resources
from typing import List, Optional

# template name -> sub-folder of this package
TEMPLATES = {
    "epd_skeleton": "epd",
    "bridges_common": "epd",
    "sensitivity_epd": "epd",
}


def names() -> List[str]:
    return sorted(TEMPLATES)


def read(name: str) -> Optional[str]:
    """The text of a template, or None if there is none by that name."""
    key = (name or "").strip()
    if key.lower().endswith(".baslca"):
        key = key[:-len(".baslca")]
    key = key.lower()
    folder = TEMPLATES.get(key)
    if folder is None:
        return None
    path = resources.files(__name__).joinpath(folder, f"{key}.baslca")
    return path.read_text(encoding="utf-8")
