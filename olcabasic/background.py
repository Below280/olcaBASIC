"""
Which folders hold background data.

olcaBASIC treats as its own the folders a program builds in (SET
PROCESS FOLDER, SET FLOW FOLDER, CDIR, MKDIR, the EPD's FOLDER). That
alone would let a program declare a background folder its own, and then
use, edit, move or delete background data as if it were the model's.

Background databases file their datasets under classification codes:
ecoinvent and the databases built like it (EN15804GD, HiQLCD, BAFU)
under ISIC sections, 'A:Agriculture...' to 'U:...'; the US databases
(LCA Commons, US LCI) under NAICS sectors, '11: ...' to '92: ...'. A top
folder named like that is background, whatever a program says, and
olcaBASIC does not build in it, edit it, move things into or out of it,
or delete from it. ecoinvent's 'Recycled content cut-off' folder is
background too. Model folders such as '00: My model' are not
classification codes ('00' is no NAICS sector).
"""

import re

# openLCA does not tell folder names apart by case alone, so neither
# does this
_ISIC = re.compile(r"^[A-U]\s*:", re.IGNORECASE)
# Top folders of background databases that carry no classification code
# (ecoinvent files its cut-off dummies for recycled content here).
_NAMED = {"recycled content cut-off"}
_NAICS = re.compile(r"^(1[1-9]|[2-9]\d)(\s*-\s*\d{2})?\s*:")


def top_folder(category: str) -> str:
    return (category or "").strip().strip("/").split("/")[0].strip()


def is_background_folder(category: str) -> bool:
    """True when the top folder of `category` is a classification code
    of a background database."""
    top = top_folder(category)
    return bool(top) and bool(_ISIC.match(top) or _NAICS.match(top)
                              or top.lower() in _NAMED)


REFUSAL_HINT = ("Background data is filed under classification codes "
                "(ISIC 'A:' to 'U:', NAICS '11:' to '92:'), and olcaBASIC "
                "does not change it. Build in a folder of your own, such as "
                "'00: My model', and reach background data through a "
                "BRIDGE.")
