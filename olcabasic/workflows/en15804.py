"""
Named values of EN 15804+A2 and the standards it leans on, as the EPD
workflow uses them.

Clause and table numbers are given so that each value can be looked
up; none of the standards' text is reproduced here. Checked against
EN 15804:2012+A2:2019 (Tables 3 and 4, 6.3.8.3, 6.4.3.2, 6.4.4, 7.2.5,
Annex C.2.4, Annex E) and EN 16485:2014 (6.3.4.2, 6.3.4.5) on
12/11/2026.

The codes are the abbreviations openLCA's EN 15804 method packs put in
brackets at the end of each impact category's name. A programme
profile can replace any of these values with its own.
"""

import re
from typing import Dict, Optional, Tuple

# Table 3: core environmental impact indicators
CORE_INDICATOR_CODES: Tuple[str, ...] = (
    "GWP-total", "GWP-fossil", "GWP-biogenic", "GWP-luluc", "ODP", "AP",
    "EP-freshwater", "EP-marine", "EP-terrestrial", "POCP", "ADPE", "ADPF",
    "WDP")

# Table 4: additional environmental impact indicators
ADDITIONAL_INDICATOR_CODES: Tuple[str, ...] = (
    "PM", "IRP", "ETP-fw", "HTP-c", "HTP-nc", "SQP")

# Other ways the same indicator is written in a category name
CODE_ALIASES: Dict[str, str] = {
    "GWP-IOBC/GHG": "GWP-GHG",
    "GWP-IOBC": "GWP-GHG",
    "ADP-minerals&metals": "ADPE",
    "ADP-minerals": "ADPE",
    "ADP-fossil": "ADPF",
}

GWP_BIOGENIC_CODE = "GWP-biogenic"

CLAUSE_INDICATORS = "EN 15804+A2, Tables 3 and 4"

# Annex E: both schemes (Tables E.1 and E.2) use the same five levels
DQ_LEVELS: Tuple[str, ...] = ("Very good", "Good", "Fair", "Poor",
                              "Very poor")
DQ_SCHEMES: Tuple[str, ...] = (
    "UN Environment Global Guidance on LCA database development",
    "Product Environmental Footprint")
DQ_ASPECTS: Tuple[str, ...] = ("GEOGRAPHY", "TECHNOLOGY", "TIME")
DQ_ASPECT_TITLES: Dict[str, str] = {
    "GEOGRAPHY": "Geographical representativeness",
    "TECHNOLOGY": "Technical representativeness",
    "TIME": "Temporal representativeness",
}
CLAUSE_DQ_SCHEME = "EN 15804+A2, 6.3.8.3 and Annex E"

# Biogenic carbon
#: kg of carbon per kg of oven-dry wood (EN 16485, 6.3.4.2)
CARBON_FRACTION_OF_DRY_WOOD = 0.5
#: kg of CO2 per kg of carbon (EN 15804+A2, 7.2.5)
CO2_PER_KG_CARBON = 44.0 / 12.0
#: the A to C balance and module D, as a share of the stored CO2
BIOGENIC_BALANCE_TOLERANCE_PCT = 0.1
#: the uptake in A1 to A3 against the declared content
BIOGENIC_CONTENT_TOLERANCE_PCT = 0.5
#: below this many kg CO2 eq. a difference is not looked at
BIOGENIC_FLOOR_KG_CO2 = 1e-9
#: a flow of the GWP-biogenic category is biogenic CO2 if its name
#: holds this (the other flows are methane and the like)
BIOGENIC_CO2_FLOW_NAME = "carbon dioxide"

CLAUSE_BIOGENIC_CONTENT = "EN 15804+A2, 6.4.4 and 7.2.5"
CLAUSE_BIOGENIC_FACTORS = "EN 15804+A2, C.2.4"
CLAUSE_BIOGENIC_UPTAKE = "EN 16485, 6.3.4.2"
CLAUSE_BIOGENIC_COPRODUCTS = "EN 15804+A2, 6.4.3.2; EN 16485, 6.3.4.2"
CLAUSE_BIOGENIC_END_OF_LIFE = "EN 16485, 6.3.4.5"

_BRACKETS = re.compile(r"\(([^()]+)\)")


def indicator_code(category_name: str) -> Optional[str]:
    """The indicator code in a category name: the last piece in round
    brackets that is a known code or another way of writing one, with
    aliases resolved. None if the name carries no such piece."""
    found = [CODE_ALIASES.get(p.strip(), p.strip())
             for p in _BRACKETS.findall(category_name or "")]
    known = set(CORE_INDICATOR_CODES + ADDITIONAL_INDICATOR_CODES) | {
        "GWP-GHG"}
    for code in reversed(found):
        if code in known:
            return code
    for code in reversed(found):
        if _CODE_SHAPE.match(code):
            return code
    return None


# A code is short and has no spaces: "AP", "GWP-total", "ETP-fw".
# "(EF 3.1)" or "(market for)" in a name is not one.
_CODE_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9&/-]{1,24}$")
