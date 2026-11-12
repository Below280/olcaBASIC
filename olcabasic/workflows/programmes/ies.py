"""
Programme profile: the International EPD System (IES).

Checked against the General Programme Instructions, version 5.1.0,
Annex A. Clause numbers are given so that each rule can be looked up;
none of the programme's text is reproduced here.

Every threshold is a named value on the profile. A later version of the
GPI, or another operator, is a new profile, not an edit to the EPD
workflow.

Programme rules are errors, not warnings, and none of them has an
override.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Tuple


@dataclass(frozen=True)
class Profile:
    """The numbers and lists the International EPD System fixes."""

    name: str = "IES"
    title: str = "International EPD System"
    document: str = "General Programme Instructions"
    gpi_versions: Tuple[str, ...] = ("5.1.0",)

    # A.3.3: declared cut-offs per module, as a share of mass or energy
    cutoff_limit_pct: float = 5.0

    # A.5.1: share of any impact indicator that may come from proxy data
    proxy_limit_pct: float = 10.0

    # A.5.2: age of primary data, in years
    primary_max_age_years: int = 5

    # A.5.3: age of the reference year of representative secondary
    # data; older data is proxy data by definition
    secondary_max_age_years: int = 10

    # A.5.4: processes above this share of the GWP-GHG result of
    # A1-A3 are declared one by one
    gwp_row_threshold_pct: float = 10.0

    # A.5.4: above this, the total share of primary data may be
    # reported as ">90%"
    primary_share_cap_pct: float = 90.0

    # A.5.4: the data quality assessment covers data that together
    # give at least this share of each indicator
    coverage_pct: float = 80.0

    # A.5.4, A.7.1: the modules whose GWP-GHG result the share of
    # primary data is calculated on
    product_stage: Tuple[str, ...] = ("A1", "A2", "A3")

    # A.7.1: modules whose processes are under the manufacturer's
    # direct control unless a process says CONTROL NONE
    direct_control_modules: FrozenSet[str] = frozenset({"A3"})

    # A.6.2: countries where the electricity market is a sub-national
    # grid, so a national mix is refused (ISO 3166 alpha-2 codes)
    subnational_countries: FrozenSet[str] = frozenset(
        {"AU", "BR", "CA", "CN", "IN", "US"})

    # A.6.2, A.7.1: the order of preference for electricity
    electricity_hierarchy: Tuple[str, ...] = (
        "CONTRACT", "RESIDUAL", "CONSUMPTION")

    # A.7.5, A.8: module D is never part of any total
    module_d_in_totals: bool = False

    # A.7.5: range of the quality adjustment factor, in per cent
    quality_factor_range: Tuple[float, float] = (0.0, 100.0)

    # Data categories (A.5.1)
    data_categories: Tuple[str, ...] = ("PRIMARY", "SECONDARY", "PROXY")

    # Where each rule comes from, for error messages and the report
    clauses: Dict[str, str] = field(default_factory=lambda: {
        "cutoff": "A.3.3",
        "data_categories": "A.5.1",
        "proxy": "A.5.1",
        "primary_age": "A.5.2",
        "secondary_age": "A.5.3",
        "data_quality": "A.5.4",
        "primary_share_statement": "A.5.4",
        "electricity": "A.6.2",
        "electricity_hierarchy": "A.7.1",
        "primary_for_own_processes": "A.7.1",
        "module_d": "A.7.5",
        "module_d_separate": "A.8",
        "location_based": "A.6.2",
    })

    def clause(self, key: str) -> str:
        """'GPI 5.1.0, A.5.1' for a rule."""
        version = self.gpi_versions[-1]
        return f"GPI {version}, {self.clauses[key]}"

    def needs_subnational_mix(self, country: str) -> bool:
        return (country or "").strip().upper() in self.subnational_countries

    def is_direct_control(self, module: str, control: str) -> bool:
        """A process is under the manufacturer's direct control if it
        says CONTROL DIRECT, or sits in a direct-control module and
        does not say CONTROL NONE."""
        control = (control or "").upper()
        if control == "DIRECT":
            return True
        if control == "NONE":
            return False
        return module in self.direct_control_modules


PROFILE = Profile()
