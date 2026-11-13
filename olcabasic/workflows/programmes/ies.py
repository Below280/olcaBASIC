"""
Programme profile: the International EPD System (IES).

Checked against the General Programme Instructions, version 5.1.0,
Annex A, and PCR 2019:14 version 1.3.1 (Annexes 2 and 3). Clause
numbers are given so that each rule can be looked up; none of the
programme's text is reproduced here.

Every threshold is a named value on the profile. A later version of the
GPI, or another operator, is a new profile, not an edit to the EPD
workflow.

Programme rules are errors, not warnings, and none of them has an
override.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Tuple

from .. import en15804


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

    # A.5.1, A.5.4: the proxy limit and the coverage run over the
    # declared environmental impact indicators: the core and additional
    # indicators of EN 15804+A2 (Tables 3 and 4) and the GWP-GHG
    # indicator the PCR adds. Resource use, waste and output flow
    # indicators are not impact indicators. The codes are the ones in
    # brackets at the end of each category name in openLCA.
    impact_indicator_codes: Tuple[str, ...] = (
        en15804.CORE_INDICATOR_CODES + ("GWP-GHG",)
        + en15804.ADDITIONAL_INDICATOR_CODES)

    # The core indicators and GWP-GHG have to be found in the method;
    # the additional ones are counted when the method has them
    required_indicator_codes: Tuple[str, ...] = (
        en15804.CORE_INDICATOR_CODES + ("GWP-GHG",))

    # The code of the indicator the 10% rows and the share of primary
    # data are calculated on
    gwp_ghg_code: str = "GWP-GHG"

    # The split of a module between its processes and bridges has to
    # add up to the module's total: the largest gap allowed, as a share
    # of the total, and the size of total below which it is not looked
    # at. A model check, not a clause of the GPI.
    residual_tolerance_pct: float = 0.1
    residual_floor: float = 1e-9

    # A.5.4: the scheme and the levels of the representativeness
    # ratings (EN 15804+A2, Annex E; both schemes there use these)
    dq_scheme: str = en15804.DQ_SCHEMES[0]
    dq_levels: Tuple[str, ...] = en15804.DQ_LEVELS

    # PCR 2019:14, Annex 2: biogenic carbon balances
    biogenic_balance_tolerance_pct: float = (
        en15804.BIOGENIC_BALANCE_TOLERANCE_PCT)
    biogenic_content_tolerance_pct: float = (
        en15804.BIOGENIC_CONTENT_TOLERANCE_PCT)

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

    # Section 7: the EPD document. Names and addresses are facts the
    # document states; the statements the programme requires word for
    # word are not reproduced here: EPD DOCUMENT reads them from a file
    # the user keeps (STATEMENTS), by these keys, and marks the document
    # as a draft while any is missing.
    programme_title: str = "The International EPD System"
    operator_name: str = "EPD International AB"
    programme_website: str = "www.environdec.com"
    statement_keys: Dict[str, str] = field(default_factory=lambda: {
        "cover": "7.4.1 (cover page: updates and the latest version)",
        "iso14025": "7.4.1 (cover page: conformity with ISO 14025)",
        "operator": "7.4.2.1 (programme operator's address)",
        "ownership": "7.4.2.4 (ownership and liability)",
        "comparability": "7.4.2.4 (comparability of EPDs)",
        "relative": "7.4.7 (results are relative expressions)",
        "end_of_life": "7.4.7 (consider the end-of-life results)",
        "primary_share": "A.5.4 (how the share of primary data is "
                         "calculated)",
    })
    # 7.4.5: a substance of very high concern above this share of the
    # product's mass is declared
    svhc_declare_pct: float = 0.1
    # 7.2: significant digits in result tables
    result_digits: int = 2

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
        "impact_indicators": "A.5.4",
        "ratings": "A.5.4",
        "document": "7.4",
        "content": "7.4.5",
        "lca_information": "7.4.6",
        "units": "7.2",
    })

    # Rules that come from the PCR, not the GPI
    pcr_clauses: Dict[str, str] = field(default_factory=lambda: {
        "biogenic": "PCR 2019:14, Annex 2",
        "primary_energy": "PCR 2019:14, Annex 3",
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
