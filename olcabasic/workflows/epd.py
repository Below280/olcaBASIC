"""
The EPD workflow: EN 15804+A2 as commands.

    EPD "name" ... END EPD        the definition, checked as it is read
    MODULE A1 ... TOTAL ... END MODULE
    EPD SYSTEMS                   one product system per module
    EPD CHECK                     validate, and list what is missing
    EPD CALCULATE                 every module with the EPD method
    EPD DATA QUALITY              the programme's data quality arithmetic
    EPD REPORT "file.csv"         indicator by module, with the header

The rules of the standard are enforced here. The rules a programme
operator adds are in a profile (workflows/programmes), chosen with
PROGRAMME in the EPD block.

Clause numbers are given so each rule can be looked up. None of the
text of EN 15804, of a programme's instructions or of a PCR is
reproduced in this file: they are copyright.

Where the data sits in openLCA
------------------------------
What a DATA, CONTROL or ELECTRICITY line declares is stored on the
process as tags of the form "epd:key=value" (epd:data=PRIMARY,
epd:year=2025, epd:electricity=RESIDUAL and so on). olca_schema's
process documentation has no field for a data category or a source
type, so tags are the one place that holds all of it and can be read
back. The reference year also goes into the documentation's own
"valid from" and "valid until" dates, which is the field openLCA has
for it. openLCA separates tags with commas, so a comma inside a value
is stored as a semicolon.
"""

import csv
import datetime
import re
from typing import Dict, List, Optional

from ..errors import BasicError
from . import programmes

MODULE_ORDER = ["A1", "A2", "A3", "A4", "A5",
                "B1", "B2", "B3", "B4", "B5", "B6", "B7",
                "C1", "C2", "C3", "C4", "D"]
PRODUCT_STAGE = ("A1", "A2", "A3")
END_OF_LIFE = ("C1", "C2", "C3", "C4")
C_AND_D = END_OF_LIFE + ("D",)
OPTIONS = ("A4", "A5")
USE_STAGE = ("B1", "B2", "B3", "B4", "B5", "B6", "B7")

# The EN 15804+A2 method in openLCA's LCIA packs, and its size.
EPD_METHOD = "EN15804+A2 (EF 3.1)"
EXPECTED_CATEGORIES = 38
# The method of that family with the shorter indicator list.
SHORT_METHOD = "Environment | EN15804+A2 (EF v3.1)"

CLAUSE_MODULES = "EN 15804+A2, clause 5.2"

TAG_PREFIX = "epd"
BRIDGES_FOLDER = "Bridges"
# Global parameter that switches bridges to their location-based provider
LOCATION_SWITCH = "epd_location_based"
# Modules whose processes are under direct control when no programme
# profile says otherwise
DEFAULT_DIRECT_CONTROL = frozenset({"A3"})

# The five EPD types, named as in EN 15804+A2 clause 5.2 (with a hyphen
# for the module ranges).
TYPE_GATE_CD = "Cradle to gate with modules C1-C4 and module D"
TYPE_OPTIONS_CD = ("Cradle to gate with options, modules C1-C4, and "
                   "module D")
TYPE_GRAVE = "Cradle to grave and module D"
TYPE_GATE = "Cradle to gate"
TYPE_GATE_OPTIONS = "Cradle to gate with options"

CHECK_CAVEAT = (
    "  EPD CHECK looks at structure and declarations only: it does not "
    "show that the amounts or the results are right.")


def _norm(text: str) -> str:
    return re.sub(r"[\s+_-]", "", (text or "").lower())


def _fmt(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 1e5 or abs(value) < 1e-3:
        return f"{value:.4e}"
    return f"{value:.5g}"


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def tag_value(text) -> str:
    """A value as it is stored in a tag (openLCA splits tags at commas)."""
    return str(text).replace(",", ";").replace("\n", " ").strip()


def provenance_tags(prov: Optional[Dict], eval_str) -> Dict[str, str]:
    """The tags a DATA line becomes."""
    if not prov:
        return {}
    tags = {"data": prov["category"],
            "source": tag_value(eval_str(prov["source"])),
            "provider": tag_value(eval_str(prov["provider"])),
            "year": str(int(prov["year"])),
            "reason": None, "share": None}
    if "reason" in prov:
        tags["reason"] = tag_value(eval_str(prov["reason"]))
    if "share" in prov:
        tags["share"] = f"{prov['share']:g}"
    return tags


def provenance_documentation(prov: Optional[Dict]) -> Optional[Dict]:
    if not prov:
        return None
    year = int(prov["year"])
    return {"valid_from": f"{year}-01-01", "valid_until": f"{year}-12-31"}


# ── the definition ───────────────────────────────────────────

def epd_type(modules: List[str], exempt: bool) -> str:
    """The EPD type that follows from the declared modules."""
    has = set(modules)
    options = any(m in has for m in OPTIONS)
    use = any(m in has for m in USE_STAGE)
    if exempt:
        return TYPE_GATE_OPTIONS if options else TYPE_GATE
    if all(m in has for m in OPTIONS + USE_STAGE):
        return TYPE_GRAVE
    if options or use:
        return TYPE_OPTIONS_CD
    return TYPE_GATE_CD


def check_definition(name: str, f: Dict, lines: Dict, line: int) -> Dict:
    """Check everything about an EPD block that does not need openLCA.

    f holds the fields of the block with their expressions already
    turned into values; lines maps each field to its line. Returns the
    definition as a dictionary, or raises BasicError at the line of
    the field that is wrong."""
    def at(key):
        return lines.get(key, line)

    if not (name or "").strip():
        raise BasicError("The EPD needs a name.", line,
                         hint='For example: EPD "Concrete block"')

    required = (
        ("unit_kind", "DECLARED UNIT", "DECLARED UNIT 1, m3"),
        ("method", "METHOD", f'METHOD "{EPD_METHOD}"'),
        ("folder", "FOLDER", f'FOLDER "00: {name} EPD"'),
        ("modules", "MODULES", "MODULES A1, A2, A3, C1, C2, C3, C4, D"),
        ("biogenic", "BIOGENIC CARBON", "BIOGENIC CARBON NO (or YES)"),
    )
    for key, label, example in required:
        if key not in f:
            raise BasicError(
                f"The EPD block has no {label} line.", line,
                hint=f"Add it before END EPD. For example: {example}")

    # Modules
    modules = [m.upper() for m in f["modules"]]
    for m in modules:
        if m not in MODULE_ORDER:
            raise BasicError(
                f"'{m}' is not a module.", at("modules"),
                hint="Modules are A1 to A5, B1 to B7, C1 to C4 and D.")
    repeated = sorted({m for m in modules if modules.count(m) > 1})
    if repeated:
        raise BasicError(
            f"MODULES names {', '.join(repeated)} more than once.",
            at("modules"), hint="Name each module once.")
    modules = [m for m in MODULE_ORDER if m in modules]
    missing_a = [m for m in PRODUCT_STAGE if m not in modules]
    if missing_a:
        raise BasicError(
            f"MODULES leaves out {', '.join(missing_a)}. Every EPD declares "
            f"A1, A2 and A3 ({CLAUSE_MODULES}).", at("modules"),
            hint="Add them to the MODULES line.")

    exempt = f.get("exempt")
    declared_cd = [m for m in C_AND_D if m in modules]
    if exempt:
        if declared_cd:
            raise BasicError(
                f"EXEMPT C AND D is given, but MODULES declares "
                f"{', '.join(declared_cd)}. The exemption covers C1 to C4 "
                f"and D together ({CLAUSE_MODULES}).", exempt.get("line", line),
                hint="Either take C1 to C4 and D out of MODULES, or remove "
                     "the EXEMPT block and declare all five.")
        wanted = (("integrated", "INTEGRATED"),
                  ("not_identifiable", "NOT IDENTIFIABLE"),
                  ("eol_scenarios", "END OF LIFE SCENARIOS"))
        for key, label in wanted:
            if not str(exempt.get(key, "")).strip():
                raise BasicError(
                    f"EXEMPT C AND D needs {label} \"text\" "
                    f"({CLAUSE_MODULES}).", exempt.get("line", line),
                    hint="The exemption needs all three: INTEGRATED \"why "
                         "the product cannot be separated at end of life\", "
                         "NOT IDENTIFIABLE \"why it is no longer "
                         "identifiable\" and END OF LIFE SCENARIOS \"where "
                         "they can be found\".")
        if f["biogenic"]:
            raise BasicError(
                f"A product that contains biogenic carbon cannot leave out "
                f"C1 to C4 and D ({CLAUSE_MODULES}).", at("biogenic"),
                hint="Remove the EXEMPT block and declare C1, C2, C3, C4 "
                     "and D.")
        used = [m for m in USE_STAGE if m in modules]
        if used:
            raise BasicError(
                f"MODULES declares {', '.join(used)} with EXEMPT C AND D. "
                f"The exempt EPD types cover A1 to A3, with A4 and A5 as "
                f"options ({CLAUSE_MODULES}).", at("modules"),
                hint="Take the B modules out, or remove the EXEMPT block "
                     "and declare C1 to C4 and D.")
    elif len(declared_cd) != len(C_AND_D):
        missing = [m for m in C_AND_D if m not in modules]
        if declared_cd:
            raise BasicError(
                f"MODULES declares {', '.join(declared_cd)} but not "
                f"{', '.join(missing)}. C1 to C4 and D are declared "
                f"together or not at all ({CLAUSE_MODULES}).", at("modules"),
                hint="Add the missing modules to the MODULES line.")
        raise BasicError(
            f"MODULES leaves out C1 to C4 and D. Every EPD declares them "
            f"unless the product meets the exemption ({CLAUSE_MODULES}).",
            at("modules"),
            hint="Add C1, C2, C3, C4, D to the MODULES line. If the "
                 "product meets all the conditions of the exemption, add "
                 "an EXEMPT C AND D block instead (HELP EPD).")

    kind = epd_type(modules, bool(exempt))

    # Declared or functional unit
    if f["unit_kind"] == "FUNCTIONAL" and kind in (TYPE_GATE_CD, TYPE_GATE):
        raise BasicError(
            f"FUNCTIONAL UNIT is not allowed for this EPD type "
            f"({kind.lower()}): it takes a declared unit "
            f"({CLAUSE_MODULES}).", at("unit_kind"),
            hint=f"Write DECLARED UNIT {f.get('unit_amount', 1):g}, "
                 f"{f.get('unit', 'kg')} instead.")
    amount = f.get("unit_amount")
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise BasicError(
            "The amount of the declared unit must be a number above zero.",
            at("unit_kind"), hint="For example: DECLARED UNIT 1, m3")

    # Programme
    profile = None
    programme = str(f.get("programme", "")).strip()
    if programme:
        profile = programmes.get(programme)
        if profile is None:
            raise BasicError(
                f"There is no programme profile called '{programme}'.",
                at("programme"),
                hint="Profiles: " + ", ".join(
                    f'PROGRAMME "{n}"' for n in programmes.names())
                     + ". Leave the line out to apply EN 15804+A2 alone.")
        gpi = str(f.get("gpi", "")).strip()
        if gpi and gpi not in profile.gpi_versions:
            raise BasicError(
                f"The {profile.name} profile holds the rules of GPI "
                f"{', '.join(profile.gpi_versions)}, not {gpi}.",
                at("programme"),
                hint=f'Write PROGRAMME "{profile.name}" GPI '
                     f'"{profile.gpi_versions[-1]}". Rules from another '
                     f'version are not checked.')

    # Method, by name
    method = str(f["method"]).strip()
    if _norm(method).endswith(_norm("EN15804+A2 (EF v3.1)")):
        raise BasicError(
            f"'{method}' is not the EPD method: it holds a shorter list of "
            f"indicators than an EPD reports.", at("method"),
            hint=f'Use METHOD "{EPD_METHOD}".')
    if "en15804" not in _norm(method):
        raise BasicError(
            f"'{method}' is not an EN 15804+A2 method, and an EPD is "
            f"calculated with one.", at("method"),
            hint=f'Use METHOD "{EPD_METHOD}". FIND METHOD "EN15804" lists '
                 f'what the database holds.')
    expected = f.get("expected_categories", EXPECTED_CATEGORIES)
    if not isinstance(expected, int) or expected < 1:
        raise BasicError("CATEGORIES needs a whole number above zero.",
                         at("method"))

    # Cut-offs
    cutoffs = []
    sums: Dict[str, float] = {}
    for c in f.get("cutoffs", []):
        module = c["module"].upper()
        if module not in modules:
            raise BasicError(
                f"CUTOFF names module {module}, which is not in MODULES.",
                c["line"], hint="Cut-offs are declared per declared module.")
        if not 0 <= c["percent"] <= 100:
            raise BasicError("A cut-off is a percentage between 0 and 100.",
                             c["line"])
        sums[module] = sums.get(module, 0.0) + c["percent"]
        cutoffs.append({"module": module, "item": str(c["item"]),
                        "percent": float(c["percent"]), "line": c["line"]})
    if profile is not None:
        for module, total in sums.items():
            if total > profile.cutoff_limit_pct:
                first = next(c for c in cutoffs if c["module"] == module)
                raise BasicError(
                    f"The cut-offs declared for {module} add up to "
                    f"{total:g}%, above the limit of "
                    f"{profile.cutoff_limit_pct:g}% per module "
                    f"({profile.clause('cutoff')}).", first["line"],
                    hint="Model more of what was left out until the "
                         "declared cut-offs are within the limit.")

    return {
        "name": name.strip(), "modules": modules, "type": kind,
        "unit_kind": f["unit_kind"], "unit_amount": float(amount),
        "unit": f["unit"], "method": method, "expected_categories": expected,
        "folder": str(f["folder"]).strip("/ "), "biogenic": bool(f["biogenic"]),
        "exempt": ({k: str(v) for k, v in exempt.items() if k != "line"}
                   if exempt else None),
        "programme": profile.name if profile else "",
        "gpi": (str(f.get("gpi", "")).strip()
                or (profile.gpi_versions[-1] if profile else "")),
        "pcr": str(f.get("pcr", "")).strip(),
        "pcr_version": str(f.get("pcr_version", "")).strip(),
        "database": str(f.get("database", "")).strip(),
        "database_version": str(f.get("database_version", "")).strip(),
        "cutoffs": cutoffs,
        "gwp_indicator": str(f.get("gwp_indicator", "")).strip(),
    }


def field_values(stmt, eval_str, eval_num) -> Dict:
    """The fields of an EpdStmt with their expressions evaluated."""
    f = dict(stmt.fields)
    out = {}
    for key, value in f.items():
        if key in ("modules", "biogenic", "unit_kind", "unit",
                   "expected_categories"):
            out[key] = value
        elif key == "unit_amount":
            out[key] = eval_num(value)
        elif key == "exempt":
            out[key] = {k: (v if k == "line" else eval_str(v))
                        for k, v in value.items()}
        elif key == "cutoffs":
            out[key] = [{"module": c["module"], "item": eval_str(c["item"]),
                         "percent": c["percent"], "line": c["line"]}
                        for c in value]
        else:
            out[key] = eval_str(value)
    return out


# ── the workflow ─────────────────────────────────────────────

class EpdWorkflow:
    """The active EPD of a session: its definition and how far the
    work has got. Held in runtime.epd."""

    today = staticmethod(datetime.date.today)

    def __init__(self, interp, definition: Dict, categories: List[Dict]):
        self.i = interp
        self.d = definition
        self.profile = (programmes.get(definition["programme"])
                        if definition["programme"] else None)
        self.categories = categories
        self.modules: Dict[str, Dict] = {}
        self.check_state = ""           # "", "passed", "failed", "skipped"
        self.check_reason = ""
        self.check_date = ""
        self.results: Dict[str, Dict[str, float]] = {}
        self.units = {c["name"]: c["unit"] for c in categories}
        self.dq: Optional[Dict] = None
        self.reported = False           # EPD REPORT has passed
        self.current: Optional[Dict] = None      # process being built
        self._notes: List[str] = []
        self.gwp_indicator = self._find_gwp(definition["gwp_indicator"])

    # ── small helpers ────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.d["name"]

    @property
    def folder(self) -> str:
        return self.d["folder"]

    @property
    def bridge(self):
        return self.i.bridge

    @property
    def out(self):
        return self.i.out

    def module_folder(self, code: str) -> str:
        return f"{self.folder}/{code}"

    @property
    def bridges_folder(self) -> str:
        return f"{self.folder}/{BRIDGES_FOLDER}"

    def in_folder(self, category: str) -> bool:
        cat = (category or "").strip("/").lower()
        base = self.folder.lower()
        return cat == base or cat.startswith(base + "/")

    def _find_gwp(self, given: str) -> str:
        names = [c["name"] for c in self.categories]
        if given:
            return given if given in names else ""
        hits = [n for n in names if "gwp-ghg" in n.lower()
                or re.search(r"\bghg\b", n.lower())]
        return hits[0] if len(hits) == 1 else ""

    def _tags(self, process_id: str) -> Dict[str, str]:
        got = self.bridge.get_process_tags(process_id, TAG_PREFIX)
        return got.get("tags", {}) if "error" not in got else {}

    def _control_of(self, module: str, control: str) -> bool:
        if self.profile is not None:
            return self.profile.is_direct_control(module, control)
        control = (control or "").upper()
        if control in ("DIRECT", "NONE"):
            return control == "DIRECT"
        return module in DEFAULT_DIRECT_CONTROL

    def _reset_progress(self):
        """Anything built or changed makes earlier checks and results
        out of date."""
        self.check_state = ""
        self.check_reason = ""
        self.results = {}
        self.dq = None
        self.reported = False

    # ── EPD ... END EPD ──────────────────────────────────────

    @classmethod
    def define(cls, interp, stmt):
        interp._require_bridge(stmt.line)
        name = interp._eval_str(stmt.name)
        fields = field_values(stmt, interp._eval_str,
                              lambda e: interp._eval(e))
        d = check_definition(name, fields, stmt.lines, stmt.line)
        at = lambda key: stmt.lines.get(key, stmt.line)   # noqa: E731

        # The method must exist under exactly that name and be the
        # size an EN 15804+A2 indicator set is.
        interp._at(at("method"))
        d["method"] = interp._method(d["method"], at("method"))
        cats = interp.bridge.get_method_categories(d["method"])
        if "error" in cats:
            raise BasicError(cats["error"], at("method"))
        if cats["count"] != d["expected_categories"]:
            raise BasicError(
                f"'{d['method']}' has {cats['count']} impact categories; "
                f"the EPD indicator set has {d['expected_categories']}.",
                at("method"),
                hint=f'Use METHOD "{EPD_METHOD}". If this method is the '
                     f'full indicator set under another name, say how many '
                     f'categories to expect: METHOD "{d["method"]}" '
                     f'CATEGORIES {cats["count"]}.')
        if d["gwp_indicator"] and d["gwp_indicator"] not in [
                c["name"] for c in cats["categories"]]:
            raise BasicError(
                f"GWP INDICATOR '{d['gwp_indicator']}' is not a category of "
                f"'{d['method']}'.", at("gwp_indicator"),
                hint="Give the category's full name. SHOW METHOD "
                     f"\"{d['method']}\" lists them.")

        old = interp.runtime.epd
        epd = cls(interp, d, cats["categories"])
        interp.runtime.epd = epd
        interp.runtime.epd_module = ""
        # The folder tree: one folder per declared module, and Bridges.
        pending = interp.runtime.pending_folders
        pending.add(epd.bridges_folder)
        for code in d["modules"]:
            pending.add(epd.module_folder(code))

        out = interp.out
        if old is not None:
            out.write(f"  NOTE: this replaces the EPD '{old.name}' that was "
                      f"active. Its checks and results are set aside.")
        out.write(f"  EPD: {d['name']}")
        out.write(f"  Type: {d['type']}")
        out.write(f"  {d['unit_kind'].capitalize()} unit: "
                  f"{d['unit_amount']:g} {d['unit']}")
        out.write(f"  Method: {d['method']} ({cats['count']} categories)")
        out.write(f"  Modules: {', '.join(d['modules'])}")
        out.write(f"  Folders: {d['folder']}/ "
                  + ", ".join(d["modules"] + [BRIDGES_FOLDER]))
        if epd.profile is not None:
            out.write(f"  Programme: {epd.profile.title} "
                      f"(GPI {d['gpi']}). Its rules are errors, with no "
                      f"override.")
        else:
            out.write("  NOTE: no PROGRAMME line, so only the rules of "
                      "EN 15804+A2 are applied. A programme operator adds "
                      "its own.")
        if d["exempt"]:
            out.write("  C1 to C4 and D are left out under the exemption; "
                      "the justification goes in the report.")
        interp._emit("epd_define", {k: v for k, v in d.items()})
        return epd

    # ── PROCESS inside MODULE ────────────────────────────────

    def begin_process(self, stmt, name: str):
        """Called before a PROCESS inside a MODULE block is built.
        Returns the name and folder it gets."""
        code = self.i.runtime.epd_module
        if stmt.folder is not None:
            raise BasicError(
                f"FOLDER is not used inside MODULE {code}: the EPD puts "
                f"the process in '{self.module_folder(code)}'.", stmt.line,
                hint="Remove the FOLDER line.")
        plain = name.strip()
        m = re.match(r"^([A-D]\d?)\s*([|:])\s*(.+)$", plain)
        if m and m.group(1).upper() in MODULE_ORDER:
            if m.group(1).upper() != code or m.group(2) == ":":
                raise BasicError(
                    f"'{plain}' already carries a module prefix. Inside "
                    f"MODULE {code} the name is given without one.",
                    stmt.line,
                    hint=f"Write MAKE PROCESS \"{m.group(3)}\": it becomes "
                         f"\"{code} | {m.group(3)}\".")
            plain = m.group(3).strip()
        control = stmt.control or ""
        direct = self._control_of(code, control)
        if self.profile is not None:
            if not stmt.provenance:
                raise BasicError(
                    f"The process '{plain}' has no DATA line. Under "
                    f"PROGRAMME \"{self.profile.name}\" every process and "
                    f"bridge declares where its data comes from "
                    f"({self.profile.clause('data_quality')}).", stmt.line,
                    hint='Add a line inside the block, for example: DATA '
                         'PRIMARY SOURCE "Collected" PROVIDER "EPD owner" '
                         'YEAR 2025')
            if direct and stmt.provenance["category"] != "PRIMARY":
                raise BasicError(
                    f"'{plain}' is under the manufacturer's direct control "
                    f"and declares DATA {stmt.provenance['category']}. "
                    f"Processes under direct control take primary data "
                    f"({self.profile.clause('primary_for_own_processes')}).",
                    stmt.provenance.get("line", stmt.line),
                    hint="Declare DATA PRIMARY with the collected data, or "
                         "mark the process CONTROL NONE if the "
                         "manufacturer does not control it.")
        self._notes = []
        self.current = {"module": code, "name": plain, "direct": direct,
                        "control": "DIRECT" if direct else "NONE"}
        return f"{code} | {plain}", self.module_folder(code)

    def check_provider(self, info: Dict, line: int):
        """Called for every provider a PROCESS inside a MODULE names."""
        code = self.i.runtime.epd_module
        bridged = self.i._is_bridge(info["name"], info["category"])
        if not bridged and not self.in_folder(info["category"]):
            raise BasicError(
                f"'{info['name']}' is a background process. Inside MODULE "
                f"{code} an input comes from a bridge, or from a process "
                f"in the EPD folder '{self.folder}'.", line,
                hint=f"Make a bridge to it first: BRIDGE \"short name\", "
                     f"unit ... PROVIDER \"{info['id']}\" ... END BRIDGE. "
                     f"Then INPUT USE PROCESS \"BRIDGE | short name | "
                     f"unit\".")
        if not bridged:
            seg = info["category"].strip("/").split("/")[-1].upper()
            if seg in MODULE_ORDER and seg != code:
                # said once the process is built (this is also called
                # on the look-up pass, whose output is not shown)
                text = (f"  WARNING: MODULE {code} uses '{info['name']}' "
                        f"from module {seg}. Its impacts are then counted "
                        f"in both modules.")
                if text not in self._notes:
                    self._notes.append(text)
            return
        tags = self._tags(info["id"])
        current = self.current or {}
        if (self.profile is not None
                and tags.get("electricity") == "CONSUMPTION"
                and current.get("direct")
                and code in self.profile.product_stage):
            raise BasicError(
                f"'{info['name']}' is a consumption-mix electricity bridge, "
                f"and '{current.get('name', 'this process')}' in {code} is "
                f"under the manufacturer's direct control. A consumption "
                f"mix is not allowed there "
                f"({self.profile.clause('electricity_hierarchy')}).", line,
                hint="Use a bridge declared ELECTRICITY CONTRACT (a "
                     "contractual instrument) or ELECTRICITY RESIDUAL (the "
                     "residual mix of the market). If the manufacturer "
                     "does not control this process, mark it CONTROL NONE.")

    def end_process(self, stmt, result: Optional[Dict]):
        """Called after a PROCESS inside a MODULE has been built."""
        current, self.current = self.current, None
        notes, self._notes = self._notes, []
        for text in notes:
            self.out.write(text)
        if not result or not current:
            return
        code = current["module"]
        state = self.modules.setdefault(code, {"subs": []})
        entry = {"id": result["process_id"], "name": result["process_name"]}
        if entry not in state["subs"]:
            state["subs"].append(entry)
        if not result.get("already_existed"):
            tags = {"module": code, "role": "process",
                    "control": current["control"]}
            tags.update(provenance_tags(stmt.provenance, self.i._eval_str))
            done = self.bridge.set_process_tags(
                result["process_id"], tags, TAG_PREFIX,
                provenance_documentation(stmt.provenance))
            if "error" in done:
                raise BasicError(done["error"], stmt.line)
        self._reset_progress()

    # ── BRIDGE while an EPD is active ────────────────────────

    def check_bridge(self, stmt, name: str, provider_name: str):
        """Programme rules for a BRIDGE block."""
        if self.profile is None:
            return
        p = self.profile
        if not stmt.provenance:
            raise BasicError(
                f"The bridge '{name}' has no DATA line. Under PROGRAMME "
                f"\"{p.name}\" every process and bridge declares where its "
                f"data comes from ({p.clause('data_quality')}).", stmt.line,
                hint='Add a line inside the block, for example: DATA '
                     'SECONDARY SOURCE "Database" PROVIDER "ecoinvent 3.11" '
                     'YEAR 2024')
        looks = "electricity" in f"{name} {provider_name}".lower()
        if looks and not stmt.electricity:
            raise BasicError(
                f"The bridge '{name}' supplies electricity but does not say "
                f"how it is modelled ({p.clause('electricity')}).",
                stmt.line,
                hint='Add ELECTRICITY CONTRACT, ELECTRICITY RESIDUAL or '
                     'ELECTRICITY CONSUMPTION, and COUNTRY "code", inside '
                     'the block.')
        if not stmt.electricity:
            return
        country = self.i._eval_str(stmt.country).strip().upper()
        region = (self.i._eval_str(stmt.region).strip()
                  if stmt.region is not None else "")
        if (stmt.electricity in ("RESIDUAL", "CONSUMPTION")
                and p.needs_subnational_mix(country) and not region):
            raise BasicError(
                f"The bridge '{name}' uses a national electricity mix for "
                f"{country}. For that country the market is a sub-national "
                f"grid ({p.clause('electricity')}).", stmt.line,
                hint='Point the bridge at the mix of the grid region and '
                     'name it: REGION "name of the grid region".')

    # ── MODULE ... END MODULE ────────────────────────────────

    def run_module(self, stmt):
        code = stmt.code.upper()
        if code not in MODULE_ORDER:
            raise BasicError(
                f"'{stmt.code}' is not a module.", stmt.line,
                hint="Modules are A1 to A5, B1 to B7, C1 to C4 and D.")
        if code not in self.d["modules"]:
            raise BasicError(
                f"MODULE {code} is not declared in the EPD "
                f"'{self.name}' (MODULES {', '.join(self.d['modules'])}).",
                stmt.line,
                hint=f"Add {code} to the MODULES line of the EPD block, or "
                     f"remove this MODULE block.")
        if stmt.total is None:
            raise BasicError(
                f"MODULE {code} has no TOTAL line.", stmt.line,
                hint=f'Add TOTAL "name" before END MODULE: it builds the '
                     f'process "{code}: name" that adds the module up.')
        if stmt.net_flows and code != "D":
            raise BasicError(
                f"NET FLOW belongs in MODULE D, not MODULE {code}.",
                stmt.net_flows[0]["line"],
                hint="Net flows are what leaves the product system and is "
                     "credited in module D.")
        net_flows = []
        for net in stmt.net_flows:
            row = {"flow": self.i._eval_str(net["flow"]),
                   "amount": float(self.i._eval(net["amount"])),
                   "unit": net["unit"], "quality": net.get("quality")}
            low, high = (self.profile.quality_factor_range
                         if self.profile else (0.0, 100.0))
            if row["quality"] is not None and not low <= row["quality"] <= high:
                raise BasicError(
                    f"QUALITY {row['quality']:g}% is outside {low:g} to "
                    f"{high:g}%.", net["line"],
                    hint="The quality factor is a percentage.")
            net_flows.append(row)
        if code == "D" and self.profile is not None and not net_flows:
            raise BasicError(
                f"MODULE D declares no NET FLOW. Under PROGRAMME "
                f"\"{self.profile.name}\" module D states the net flow it "
                f"credits ({self.profile.clause('module_d')}).", stmt.line,
                hint='Add a line such as: NET FLOW "Steel scrap", 12, kg '
                     'QUALITY 80%')

        runtime = self.i.runtime
        if runtime.epd_module:
            raise BasicError(
                f"MODULE {code} starts inside MODULE {runtime.epd_module}.",
                stmt.line, hint="Close the first with END MODULE.")
        self.modules[code] = {"subs": [], "net_flows": net_flows}
        runtime.epd_module = code
        self.out.write(f"  Module {code}:")
        try:
            self.i._execute_block(stmt.body)
        finally:
            runtime.epd_module = ""
            self.current = None
        self.i._at(stmt.total["line"])
        self._build_total(code, stmt)
        self._reset_progress()

    def _build_total(self, code: str, stmt):
        total = stmt.total
        line = total["line"]
        plain = self.i._eval_str(total["name"]).strip()
        m = re.match(rf"^{code}\s*:\s*(.+)$", plain, re.IGNORECASE)
        if m:
            plain = m.group(1).strip()
        name = f"{code}: {plain}"
        folder = self.module_folder(code)
        state = self.modules[code]

        if "flow" in total:
            flow_name = self.i._eval_str(total["flow"])
            amount = float(self.i._eval(total["amount"]))
            unit = total["unit"]
        else:
            flow_name, amount, unit = name, self.d["unit_amount"], self.d["unit"]

        # Sub-processes that feed another sub-process of the module are
        # already counted through it.
        structures = []
        for sub in state["subs"]:
            st = self.bridge.process_structure(sub["id"])
            if "error" in st:
                raise BasicError(st["error"], line)
            structures.append(st)
        ids = {st["id"] for st in structures}
        fed = {link["flow_id"] for st in structures for link in st["links"]
               if link["provider_id"] in ids}
        exchanges = []
        self.i._require_family(line, "TOTAL")
        made = self.bridge.create_flow(flow_name, unit, folder, "product")
        if "error" in made:
            raise BasicError(f"TOTAL flow '{flow_name}': {made['error']}", line)
        exchanges.append({"flow_id": made["flow_id"], "flow_name": flow_name,
                          "unit": unit, "is_input": False, "is_qref": True,
                          "amount": amount})
        used, skipped = [], []
        for st in structures:
            q = st["qref"]
            if q is None:
                raise BasicError(
                    f"'{st['name']}' has no reference product, so TOTAL "
                    f"cannot add it up.", line,
                    hint="Give the process an OUTPUT ... PRODUCT line.")
            if q["flow_id"] in fed:
                skipped.append(st["name"])
                continue
            ex = {"flow_id": q["flow_id"], "flow_name": q["flow"],
                  "unit": q["unit"], "is_input": not q["is_input"],
                  "is_qref": False, "provider_id": st["id"]}
            formula = q["formula"]
            if formula and formula in st["parameters"]:
                ex["amount"] = float(st["parameters"][formula])
            elif formula:
                local = [n for n in st["parameters"]
                         if re.search(rf"\b{re.escape(n)}\b", formula)]
                if local:
                    raise BasicError(
                        f"The output of '{st['name']}' is the formula "
                        f"'{formula}', which uses the process's own "
                        f"parameter {local[0]}. TOTAL cannot carry that "
                        f"into the total process.", line,
                        hint="Give the output a plain number, or a "
                             "variable defined outside the PROCESS block.")
                ex["formula"] = formula
            else:
                ex["amount"] = float(q["amount"] or 0.0)
            exchanges.append(ex)
            used.append(st["name"])

        result = self.bridge.create_process(
            name, folder, exchanges, None,
            f"Total of module {code} of the EPD '{self.name}': adds up the "
            f"processes of the module. Built by olcaBASIC.")
        self.i._emit("create_process", result)
        if "error" in result:
            raise BasicError(result["error"], line)
        state["total"] = {"id": result["process_id"], "name": name,
                          "amount": amount, "unit": unit}
        if result.get("already_existed"):
            self.out.write(
                f"  WARNING: process '{name}' already exists in {folder}. "
                f"It was NOT changed. DELETE PROCESS \"{name}\" first to "
                f"rebuild it.")
        else:
            tags = {"module": code, "role": "total"}
            for n, net in enumerate(state.get("net_flows", []), 1):
                q = "" if net["quality"] is None else f"{net['quality']:g}"
                tags[f"netflow{n}"] = tag_value(
                    f"{net['flow']}|{net['amount']:g}|{net['unit']}|{q}")
            done = self.bridge.set_process_tags(result["process_id"], tags,
                                                TAG_PREFIX)
            if "error" in done:
                raise BasicError(done["error"], line)
            self.out.write(
                f"  Total created: {name} ({len(used)} "
                f"process{'es' if len(used) != 1 else ''}, "
                f"{amount:g} {unit})")
        if skipped:
            self.out.write(
                f"  NOTE: not added to the total, because another process "
                f"of {code} already takes their output: "
                + ", ".join(skipped) + ".")
        if not state["subs"]:
            self.out.write(
                f"  NOTE: MODULE {code} has no processes, so its results "
                f"will be zero.")
        listed = {s["name"] for s in state["subs"]} | {name}
        strays = [p["name"] for p in self.bridge.processes_in_folder(
            folder, deep=False) if p["name"] not in listed]
        if strays:
            self.out.write(
                f"  NOTE: '{folder}' also holds "
                + ", ".join(f"'{s}'" for s in strays[:5])
                + (" and more" if len(strays) > 5 else "")
                + ". They are not in this MODULE block, so they are not "
                  "in the total.")

    # ── finding what an earlier run built ────────────────────

    def _total_of(self, code: str) -> Optional[Dict]:
        state = self.modules.setdefault(code, {"subs": []})
        if state.get("total"):
            return state["total"]
        found = [p for p in self.bridge.processes_in_folder(
            self.module_folder(code), deep=False)
            if p["name"].upper().startswith(f"{code}:")]
        if len(found) != 1:
            return None
        st = self.bridge.process_structure(found[0]["id"])
        q = st.get("qref") if "error" not in st else None
        if not q:
            return None
        amount = q["amount"]
        if q["formula"] and q["formula"] in st["parameters"]:
            amount = st["parameters"][q["formula"]]
        state["total"] = {"id": found[0]["id"], "name": found[0]["name"],
                          "amount": float(amount or 0.0), "unit": q["unit"]}
        return state["total"]

    def _system_of(self, code: str) -> Optional[Dict]:
        state = self.modules.setdefault(code, {"subs": []})
        if state.get("system"):
            return state["system"]
        total = self._total_of(code)
        if not total:
            return None
        desc = self.bridge.find_system(total["name"])
        if desc is None or desc.name != total["name"]:
            return None
        state["system"] = {"id": desc.id, "name": desc.name}
        return state["system"]

    def _require_systems(self, line: int, command: str) -> Dict[str, Dict]:
        systems, missing = {}, []
        for code in self.d["modules"]:
            system = self._system_of(code)
            if system is None:
                missing.append(code)
            else:
                systems[code] = system
        if missing:
            raise BasicError(
                f"{command} needs a product system for every declared "
                f"module; there is none for {', '.join(missing)}.", line,
                hint="Build each module with MODULE ... TOTAL ... END "
                     "MODULE, then run EPD SYSTEMS.")
        return systems

    # ── EPD SYSTEMS ──────────────────────────────────────────

    def systems(self, line: int):
        missing = [c for c in self.d["modules"] if self._total_of(c) is None]
        if missing:
            raise BasicError(
                f"EPD SYSTEMS needs the total process of every declared "
                f"module; there is none for {', '.join(missing)}.", line,
                hint="Each declared module needs a block: MODULE code ... "
                     "TOTAL \"name\" ... END MODULE. A module with nothing "
                     "in it still gets a TOTAL line.")
        self.i._default("LINKING")
        made = []
        # One at a time: openLCA does not take product systems in parallel.
        for code in self.d["modules"]:
            total = self._total_of(code)
            self.out.write(f"  Creating product system for {total['name']}...")
            result = self.bridge.create_system(
                total["id"], "prefer_defaults", total["amount"],
                total["unit"], None, self.folder)
            self.i._emit("create_system", result)
            if "error" in result:
                raise BasicError(
                    f"Module {code}: {result['error']}", line,
                    hint=f"VALIDATE \"{total['name']}\" shows the state of "
                         f"a system that was left behind.")
            name = result.get("system_name", total["name"])
            self.modules[code]["system"] = {"id": result.get("system_id", ""),
                                            "name": name}
            if result.get("already_existed"):
                self.out.write(
                    f"  WARNING: product system '{name}' already exists and "
                    f"was reused as it is. If the module changed, DELETE "
                    f"SYSTEM \"{name}\" first, then EPD SYSTEMS again.")
            else:
                self.i._forget_validation(result.get("system_id", ""))
            for w in result.get("warnings") or []:
                self.out.write(f"  WARNING: {w}")
            self._group_module(code, line)
            made.append(name)
        self._reset_progress()
        self.out.write(f"  {len(made)} product systems ready. Next: EPD CHECK")

    def _group_module(self, code: str, line: int):
        """One analysis group per module on the module's system, named
        after the module and holding the module's own processes, so
        openLCA shows results by module (and RESULT ... BY GROUP reads
        them). What the module's processes buy in is counted with
        them."""
        system = self.modules[code]["system"]
        own = [p["id"] for p in self.bridge.processes_in_folder(
            self.module_folder(code), deep=True)]
        done = self.bridge.set_analysis_group(system["id"], code, own)
        if "error" in done:
            raise BasicError(
                f"Module {code}: could not set the analysis group on "
                f"'{system['name']}': {done['error']}", line)

    # ── EPD CHECK ────────────────────────────────────────────

    def _foreground(self) -> List[Dict]:
        """Every process in the EPD folder, with its structure and tags."""
        rows = []
        for p in self.bridge.processes_in_folder(self.folder):
            st = self.bridge.process_structure(p["id"])
            if "error" in st:
                continue
            tags = {}
            for tag in st["tags"]:
                if tag.startswith(TAG_PREFIX + ":"):
                    key, sep, value = tag[len(TAG_PREFIX) + 1:].partition("=")
                    if sep:
                        tags[key] = value
            seg = st["category"].strip("/").split("/")[-1]
            st["epd"] = tags
            st["is_bridge"] = self.i._is_bridge(st["name"], st["category"])
            st["module"] = tags.get("module") or (
                seg.upper() if seg.upper() in MODULE_ORDER else "")
            st["is_total"] = (tags.get("role") == "total" or bool(
                st["module"] and st["name"].upper().startswith(
                    st["module"] + ":")))
            rows.append(st)
        return rows

    def _programme_findings(self, rows: List[Dict]) -> List[str]:
        """What the programme profile objects to in the model as built."""
        p = self.profile
        problems = []
        by_id = {r["id"]: r for r in rows}
        for r in rows:
            tags = r["epd"]
            if r["is_total"]:
                continue
            if not tags.get("data"):
                problems.append(
                    f"'{r['name']}' has no data declaration "
                    f"({p.clause('data_quality')}). Add one with EDIT "
                    f"PROCESS \"{r['name']}\" ... DATA ... END EDIT.")
            if r["is_bridge"]:
                providers = " ".join(l["provider"] for l in r["links"])
                looks = "electricity" in f"{r['name']} {providers}".lower()
                kind = tags.get("electricity")
                if looks and not kind:
                    problems.append(
                        f"'{r['name']}' supplies electricity but does not "
                        f"say how it is modelled ({p.clause('electricity')}).")
                if kind in ("RESIDUAL", "CONSUMPTION") and \
                        p.needs_subnational_mix(tags.get("country", "")) \
                        and not tags.get("region"):
                    problems.append(
                        f"'{r['name']}' uses a national electricity mix for "
                        f"{tags.get('country')}, where the market is a "
                        f"sub-national grid ({p.clause('electricity')}).")
                continue
            direct = p.is_direct_control(r["module"], tags.get("control", ""))
            if direct and tags.get("data") and tags["data"] != "PRIMARY":
                problems.append(
                    f"'{r['name']}' is under direct control but declares "
                    f"{tags['data'].lower()} data "
                    f"({p.clause('primary_for_own_processes')}).")
            if direct and r["module"] in p.product_stage:
                for link in r["links"]:
                    other = by_id.get(link["provider_id"])
                    if other and other["epd"].get("electricity") == "CONSUMPTION":
                        problems.append(
                            f"'{r['name']}' is under direct control and "
                            f"takes electricity from the consumption-mix "
                            f"bridge '{other['name']}' "
                            f"({p.clause('electricity_hierarchy')}).")
        return problems

    def check(self, line: int, skip: bool = False, reason: str = ""):
        systems = self._require_systems(line, "EPD CHECK")
        today = self.today().strftime("%d/%m/%Y")
        if skip:
            if self.profile is not None:
                raise BasicError(
                    f"EPD CHECK SKIP is not allowed under PROGRAMME "
                    f"\"{self.profile.name}\": an EPD for a programme is "
                    f"checked, with no exceptions.", line,
                    hint="Run EPD CHECK and fix what it finds.")
            if not reason.strip():
                raise BasicError("EPD CHECK SKIP needs a reason.", line)
            self.check_state, self.check_reason = "skipped", reason.strip()
            self.check_date = today
            self.out.write(f"  EPD CHECK skipped: {reason.strip()}")
            self.out.write("  The reason is written into the EPD report.")
            self.i._emit("epd_check", {"state": "skipped", "reason": reason})
            return

        problems, notes = [], []
        for code, system in systems.items():
            result = self.bridge.validate_system(system["name"], False)
            if "error" in result:
                raise BasicError(f"Module {code}: {result['error']}", line)
            self.i._record_validation(result)
            for finding in result.get("findings", []):
                text = f"{code}: {finding['message']}"
                if finding.get("severity") == "error":
                    problems.append(text)
                elif finding.get("severity") == "warning":
                    notes.append(text)

        rows = self._foreground()
        no_pedigree, no_docs = [], []
        for r in rows:
            if r["is_bridge"] and not r["links"]:
                problems.append(
                    f"The bridge '{r['name']}' has no provider, so it "
                    f"supplies nothing.")
            if r["is_total"]:
                continue
            if r["exchanges_without_pedigree"]:
                no_pedigree.append(
                    f"{r['name']} ({r['exchanges_without_pedigree']} of "
                    f"{max(r['exchange_count'] - 1, 0)} exchanges)")
            if not r["is_bridge"] and not r["description"].strip():
                no_docs.append(r["name"])
        if self.profile is not None:
            problems.extend(self._programme_findings(rows))

        self.out.write(f"  EPD CHECK: {self.name}")
        self.out.write(f"  Product systems validated: {len(systems)}")
        for text in problems:
            self.out.write(f"  ERROR: {text}")
        for text in notes:
            self.out.write(f"  WARNING: {text}")
        if no_pedigree:
            self.out.write(f"  Missing pedigree scores ({len(no_pedigree)} "
                           f"processes):")
            for text in no_pedigree:
                self.out.write(f"    {text}")
            self.out.write("  Add them with PEDIGREE on the exchange lines, "
                           "or in openLCA.")
        if no_docs:
            self.out.write(f"  Missing description ({len(no_docs)} "
                           f"processes): " + ", ".join(no_docs))
        self.out.write(CHECK_CAVEAT)
        self.check_date = today
        self.i._emit("epd_check", {
            "state": "failed" if problems else "passed",
            "problems": problems, "warnings": notes,
            "missing_pedigree": no_pedigree, "missing_description": no_docs})
        if problems:
            self.check_state = "failed"
            raise BasicError(
                f"EPD CHECK found {len(problems)} "
                f"problem{'s' if len(problems) != 1 else ''} (listed above).",
                line,
                hint="Fix them, run EPD SYSTEMS again if a process changed, "
                     "then EPD CHECK.")
        self.check_state, self.check_reason = "passed", ""
        self.out.write("  EPD CHECK passed. Next: EPD CALCULATE")

    # ── EPD CALCULATE ────────────────────────────────────────

    def calculate(self, line: int):
        if self.check_state not in ("passed", "skipped"):
            why = ("failed" if self.check_state == "failed"
                   else "has not been run since the model last changed")
            hint = ("Run EPD CHECK first." if self.profile is not None
                    else "Run EPD CHECK first. To calculate without it, "
                         "say why: EPD CHECK SKIP \"reason\".")
            raise BasicError(
                f"EPD CALCULATE refused: EPD CHECK {why}.", line, hint=hint)
        systems = self._require_systems(line, "EPD CALCULATE")
        self.i._default("ALLOCATE")
        names = [c["name"] for c in self.categories]
        results = {}
        for code, system in systems.items():
            self.i._require_valid(system["name"], line, "EPD CALCULATE")
            self.out.write(f"  Calculating {code}: {system['name']}...")
            result = self.bridge.calculate(system["name"], self.d["method"], "")
            if "error" in result:
                raise BasicError(f"Module {code}: {result['error']}", line)
            got = {i["category"]: i["amount"] for i in result["impacts"]}
            lost = [n for n in names if n not in got]
            if lost:
                raise BasicError(
                    f"Module {code}: the calculation returned no value for "
                    f"{len(lost)} of the method's categories (first: "
                    f"'{lost[0]}').", line)
            results[code] = got
        self.results = results
        self.dq = None
        self.reported = False
        self.out.write(self._table_text(results))
        self.out.write("  Module D is shown on its own: it is never part of "
                       "a total.")
        nxt = ("EPD DATA QUALITY" if self.profile is not None
               else 'EPD REPORT "file.csv"')
        self.out.write(f"  Next: {nxt}")
        self.i._emit("epd_calculate", {
            "epd": self.name, "method": self.d["method"],
            "modules": results, "units": self.units,
            "A1-A3": self._stage_total(results)})

    def _stage_total(self, results: Dict) -> Dict[str, float]:
        return {c["name"]: sum(results[m][c["name"]] for m in PRODUCT_STAGE)
                for c in self.categories}

    def _columns(self) -> List[str]:
        cols = []
        for code in self.d["modules"]:
            cols.append(code)
            if code == "A3":
                cols.append("A1-A3")
        return cols

    def _table_rows(self, results: Dict) -> List[List]:
        stage = self._stage_total(results)
        rows = []
        for c in self.categories:
            row = [c["name"], c["unit"]]
            for col in self._columns():
                value = (stage[c["name"]] if col == "A1-A3"
                         else results[col][c["name"]])
                # ten significant figures: enough for any result, and
                # it keeps floating-point noise out of the report
                row.append(float(f"{value:.10g}"))
            rows.append(row)
        return rows

    def _table_text(self, results: Dict) -> str:
        cols = self._columns()
        width = max(len(c["name"]) for c in self.categories) + 2
        lines = ["  " + "Indicator".ljust(width) + "Unit".ljust(18)
                 + "".join(col.rjust(12) for col in cols)]
        for row in self._table_rows(results):
            lines.append("  " + row[0].ljust(width) + (row[1] or "").ljust(18)
                         + "".join(_fmt(v).rjust(12) for v in row[2:]))
        return "\n".join(lines)

    # ── EPD DATA QUALITY ─────────────────────────────────────

    def _parts(self, code: str, system: Dict, line: int,
               parameters: Optional[Dict] = None) -> Dict:
        """Split a module's result between the foreground processes
        (their direct impacts) and the bridges that feed them (their
        upstream impacts). Together they are the module's total."""
        total = self._total_of(code)
        direct, upstream, info = [], [], {}
        seen = set()
        stack = [total["id"]]
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            st = self.bridge.process_structure(pid)
            if "error" in st:
                continue
            bridged = self.i._is_bridge(st["name"], st["category"])
            mine = self.in_folder(st["category"])
            tags = self._tags(pid)
            info[pid] = {"id": pid, "name": st["name"], "module": code,
                         "tags": tags, "is_bridge": bridged,
                         "is_total": tags.get("role") == "total"
                         or pid == total["id"]}
            if bridged or not mine:
                upstream.append(pid)
                continue
            direct.append(pid)
            stack.extend(l["provider_id"] for l in st["links"])
        got = self.bridge.process_contributions(
            system["name"], self.d["method"], direct=direct,
            upstream=upstream, parameters=parameters)
        if "error" in got:
            raise BasicError(f"Module {code}: {got['error']}", line)
        parts = []
        for pid in direct:
            if pid in got["direct"]:
                parts.append(dict(info[pid], values=got["direct"][pid]))
        for pid in upstream:
            if pid in got["upstream"]:
                parts.append(dict(info[pid], values=got["upstream"][pid]))
        return {"totals": got["totals"], "parts": parts}

    def data_quality(self, line: int):
        p = self.profile
        if p is None:
            raise BasicError(
                "EPD DATA QUALITY applies a programme's rules, and the EPD "
                "block names no programme.", line,
                hint='Add PROGRAMME "IES" GPI "5.1.0" to the EPD block.')
        if not self.results:
            raise BasicError(
                "EPD DATA QUALITY needs the results.", line,
                hint="Run EPD CALCULATE first.")
        if not self.gwp_indicator:
            raise BasicError(
                f"The GWP-GHG indicator of '{self.d['method']}' could not "
                f"be picked out by name.", line,
                hint='Name it in the EPD block: GWP INDICATOR "full name of '
                     'the category".')
        systems = self._require_systems(line, "EPD DATA QUALITY")
        gwp = self.gwp_indicator
        year_now = self.today().year
        errors: List[str] = []

        split = {code: self._parts(code, systems[code], line)
                 for code in self.d["modules"]}

        # One entry per process or bridge, across the modules it is in.
        entries: Dict[str, Dict] = {}
        for code, data in split.items():
            for part in data["parts"]:
                e = entries.setdefault(part["id"], {
                    "id": part["id"], "name": part["name"],
                    "tags": part["tags"], "is_bridge": part["is_bridge"],
                    "is_total": part["is_total"], "modules": [],
                    "by_module": {}})
                e["modules"].append(code)
                e["by_module"][code] = part["values"]

        def magnitude(e, cat, codes):
            return sum(abs(e["by_module"][c].get(cat, 0.0))
                       for c in codes if c in e["by_module"])

        for e in entries.values():
            tags = e["tags"]
            category = tags.get("data", "")
            e["category"] = category
            e["effective"] = category
            e["year"] = int(tags["year"]) if tags.get("year", "").isdigit() else None
            share = tags.get("share")
            e["primary_share"] = (float(share) if share not in (None, "")
                                  else (100.0 if category == "PRIMARY" else 0.0))
            carries = any(magnitude(e, c["name"], e["modules"]) > 0
                          for c in self.categories)
            if e["is_total"] and not category:
                continue
            if not category:
                if carries:
                    errors.append(
                        f"'{e['name']}' has no data declaration, so its "
                        f"share cannot be placed ({p.clause('data_quality')}).")
                continue
            if e["year"] is None:
                continue
            age = year_now - e["year"]
            if category == "PRIMARY" and age > p.primary_max_age_years:
                errors.append(
                    f"'{e['name']}': primary data from {e['year']} is "
                    f"{age} years old; the limit is "
                    f"{p.primary_max_age_years} ({p.clause('primary_age')}).")
            if category == "SECONDARY" and age > p.secondary_max_age_years:
                e["effective"] = "PROXY"
                errors.append(
                    f"'{e['name']}': secondary data with reference year "
                    f"{e['year']} is {age} years old; the limit is "
                    f"{p.secondary_max_age_years}, and older data counts as "
                    f"proxy data ({p.clause('secondary_age')}).")

        # Share of primary data, and the rows above the threshold
        stage = [c for c in p.product_stage if c in split]
        stage_total = sum(magnitude(e, gwp, stage) for e in entries.values())
        rows, others = [], {"share": 0.0, "primary": 0.0, "count": 0}
        primary_total = 0.0
        for e in sorted(entries.values(),
                        key=lambda e: -magnitude(e, gwp, stage)):
            amount = magnitude(e, gwp, stage)
            if not stage_total or not amount:
                continue
            share = 100.0 * amount / stage_total
            primary = share * e["primary_share"] / 100.0
            primary_total += primary
            if share > p.gwp_row_threshold_pct:
                rows.append({
                    "process": e["name"],
                    "modules": [m for m in e["modules"] if m in stage],
                    "source_type": e["tags"].get("source", ""),
                    "source": e["tags"].get("provider", ""),
                    "year": e["year"], "category": e["effective"],
                    "share_of_gwp": share, "primary_share": primary})
            else:
                others["share"] += share
                others["primary"] += primary
                others["count"] += 1
        primary_text = (f">{p.primary_share_cap_pct:g}%"
                        if primary_total > p.primary_share_cap_pct
                        else _pct(primary_total))

        # Proxy data, per indicator: A to C together, D on its own
        groups = [("A to C", [c for c in self.d["modules"] if c != "D"])]
        if "D" in self.d["modules"]:
            groups.append(("D", ["D"]))
        proxy = []
        for label, codes in groups:
            for c in self.categories:
                cat = c["name"]
                whole = sum(magnitude(e, cat, codes) for e in entries.values())
                if not whole:
                    continue
                part = sum(magnitude(e, cat, codes) for e in entries.values()
                           if e["effective"] == "PROXY")
                share = 100.0 * part / whole
                if share > 0:
                    proxy.append({"modules": label, "indicator": cat,
                                  "share": share})
                if share > p.proxy_limit_pct:
                    errors.append(
                        f"Proxy data gives {_pct(share)} of '{cat}' in "
                        f"modules {label}; the limit is "
                        f"{p.proxy_limit_pct:g}% of any indicator "
                        f"({p.clause('proxy')}).")

        # What the data quality assessment has to cover
        codes = groups[0][1]
        needed: Dict[str, int] = {}
        for c in self.categories:
            cat = c["name"]
            ranked = sorted(entries.values(),
                            key=lambda e: -magnitude(e, cat, codes))
            whole = sum(magnitude(e, cat, codes) for e in ranked)
            if not whole:
                continue
            running = 0.0
            for e in ranked:
                if running >= p.coverage_pct / 100.0 * whole:
                    break
                running += magnitude(e, cat, codes)
                needed[e["name"]] = needed.get(e["name"], 0) + 1
        coverage = sorted(needed.items(), key=lambda kv: (-kv[1], kv[0]))

        out = self.out
        out.write(f"  EPD DATA QUALITY: {self.name} "
                  f"({p.title}, GPI {self.d['gpi']})")
        out.write(f"  Processes above {p.gwp_row_threshold_pct:g}% of "
                  f"'{gwp}' in A1-A3:")
        out.write("    " + "Process".ljust(44) + "Source type".ljust(16)
                  + "Source".ljust(20) + "Year".ljust(6)
                  + "Category".ljust(11) + "Share".rjust(8)
                  + "Primary".rjust(9))
        for r in rows:
            out.write("    " + r["process"][:42].ljust(44)
                      + r["source_type"][:14].ljust(16)
                      + r["source"][:18].ljust(20)
                      + str(r["year"] or "").ljust(6)
                      + r["category"].lower().ljust(11)
                      + _pct(r["share_of_gwp"]).rjust(8)
                      + _pct(r["primary_share"]).rjust(9))
        if others["count"]:
            out.write("    " + f"Other processes ({others['count']})".ljust(97)
                      + _pct(others["share"]).rjust(8)
                      + _pct(others["primary"]).rjust(9))
        out.write(f"  Share of primary data in '{gwp}', A1-A3: {primary_text}")
        if proxy:
            worst = max(proxy, key=lambda r: r["share"])
            out.write(f"  Proxy data: at most {_pct(worst['share'])} of an "
                      f"indicator ('{worst['indicator']}', modules "
                      f"{worst['modules']}); limit {p.proxy_limit_pct:g}%.")
        else:
            out.write("  Proxy data: none.")
        out.write(f"  The data quality assessment has to cover these "
                  f"({p.coverage_pct:g}% of each indicator, modules A to C):")
        for name, count in coverage:
            out.write(f"    {name} (needed for {count} of "
                      f"{len(self.categories)} indicators)")
        out.write(f"  The EPD has to carry the programme's statement on how "
                  f"the share of primary data is calculated "
                  f"({p.clause('primary_share_statement')}).")
        for text in errors:
            out.write(f"  ERROR: {text}")

        self.dq = {
            "passed": not errors, "indicator": gwp, "rows": rows,
            "others": others, "primary_share": primary_total,
            "primary_share_text": primary_text, "proxy": proxy,
            "coverage": [{"process": n, "indicators": k} for n, k in coverage],
            "errors": errors}
        self.i._emit("epd_data_quality", self.dq)
        if errors:
            raise BasicError(
                f"EPD DATA QUALITY found {len(errors)} "
                f"problem{'s' if len(errors) != 1 else ''} (listed above). "
                f"Programme rules have no override.", line,
                hint="Replace or re-declare the data, rebuild what "
                     "changed, then run EPD SYSTEMS, EPD CHECK, EPD "
                     "CALCULATE and EPD DATA QUALITY again.")
        out.write('  EPD DATA QUALITY passed. Next: EPD REPORT "file.csv"')

    # ── EPD REPORT ───────────────────────────────────────────

    def _electricity_rows(self, line: int) -> List[Dict]:
        """Electricity bridges used by processes under direct control,
        each with its GWP-GHG per kWh (from running the bridge)."""
        rows = self._foreground()
        by_id = {r["id"]: r for r in rows}
        wanted = []
        for r in rows:
            if r["is_bridge"] or r["is_total"]:
                continue
            if not self._control_of(r["module"], r["epd"].get("control", "")):
                continue
            for link in r["links"]:
                other = by_id.get(link["provider_id"])
                if other and other["epd"].get("electricity") \
                        and other not in wanted:
                    wanted.append(other)
        out = []
        for b in wanted:
            tags = b["epd"]
            value = None
            if self.gwp_indicator:
                self.out.write(f"  Running {b['name']} for 1 kWh...")
                made = self.bridge.create_system(
                    b["id"], "prefer_defaults", 1.0, "kWh", None,
                    self.bridges_folder)
                if "error" in made:
                    raise BasicError(
                        f"Electricity bridge '{b['name']}': "
                        f"{made['error']}", line,
                        hint="The climate impact per kWh comes from "
                             "running the bridge for 1 kWh, so its unit "
                             "has to convert to kWh.")
                result = self.bridge.calculate(
                    made.get("system_name", b["name"]), self.d["method"], "")
                if "error" in result:
                    raise BasicError(
                        f"Electricity bridge '{b['name']}': "
                        f"{result['error']}", line)
                value = next((i["amount"] for i in result["impacts"]
                              if i["category"] == self.gwp_indicator), None)
            approach = {"CONTRACT": "Contractual instrument",
                        "RESIDUAL": "Residual mix",
                        "CONSUMPTION": "Consumption mix"}[tags["electricity"]]
            out.append({
                "bridge": b["name"], "approach": approach,
                "energy_source": tags.get("energy_source", ""),
                "country": tags.get("country", ""),
                "region": tags.get("region", ""), "gwp_per_kwh": value})
        return out

    def _location_based(self, line: int) -> Dict:
        """The results with every electricity bridge on its
        location-based provider."""
        rows = [r for r in self._foreground()
                if r["is_bridge"] and r["epd"].get("electricity")]
        lacking = [r["name"] for r in rows
                   if r["epd"]["electricity"] != "CONSUMPTION"
                   and r["epd"].get("switch") != LOCATION_SWITCH]
        if lacking:
            raise BasicError(
                "LOCATION BASED needs a consumption-mix provider on every "
                "electricity bridge that is not one already; "
                + ", ".join(f"'{n}'" for n in lacking)
                + (" has" if len(lacking) == 1 else " have") + " none.", line,
                hint='Add LOCATION BASED PROVIDER "process name or uuid" '
                     'to the BRIDGE block, DELETE the bridge and the '
                     'processes built on it, and build them again.')
        systems = self._require_systems(line, "EPD REPORT")
        switched = any(r["epd"].get("switch") == LOCATION_SWITCH for r in rows)
        results = {}
        for code, system in systems.items():
            got = None
            if switched:
                got = self.bridge.process_contributions(
                    system["name"], self.d["method"],
                    parameters={LOCATION_SWITCH: 1.0})
                if "error" in got and "not found in the system" in got["error"]:
                    got = None          # no switched bridge in this module
                elif "error" in got:
                    raise BasicError(f"Module {code}: {got['error']}", line)
            results[code] = got["totals"] if got else self.results[code]
        return results

    def report(self, line: int, filename: str, location_based: bool = False):
        if not self.results:
            raise BasicError(
                "EPD REPORT needs the results.", line,
                hint="Run EPD CALCULATE first.")
        p = self.profile
        if p is not None and not (self.dq and self.dq["passed"]):
            raise BasicError(
                f"EPD REPORT refused: under PROGRAMME \"{p.name}\" the data "
                f"quality rules have to pass first "
                f"({p.clause('data_quality')}).", line,
                hint="Run EPD DATA QUALITY.")
        if not filename.strip():
            raise BasicError("EPD REPORT needs a file name.", line,
                             hint='For example: EPD REPORT "results.csv"')
        d = self.d
        from .. import __version__
        electricity = self._electricity_rows(line)
        second = self._location_based(line) if location_based else None

        rows: List[List] = []
        add = rows.append
        add(["EPD results"])
        add(["Product", d["name"]])
        add(["EPD type", d["type"]])
        add([f"{d['unit_kind'].capitalize()} unit",
             f"{d['unit_amount']:g} {d['unit']}"])
        add(["Method", d["method"]])
        add(["Impact categories", len(self.categories)])
        add(["Database family", self.bridge.database_family])
        add(["olcaBASIC version", __version__])
        add(["Date", self.today().strftime("%d/%m/%Y")])
        if p is not None:
            add(["Programme", f"{p.title} (GPI {d['gpi']})"])
        else:
            add(["Programme", "None named: EN 15804+A2 rules only"])
        add(["PCR", " ".join(x for x in (d["pcr"], d["pcr_version"]) if x)
             or "Not stated"])
        add(["Database", " ".join(x for x in (d["database"],
                                             d["database_version"]) if x)
             or "Not stated"])
        add(["Biogenic carbon in the product", "Yes" if d["biogenic"] else "No"])
        add(["Modules declared", ", ".join(d["modules"])])
        if d["exempt"]:
            add(["Modules C1 to C4 and D",
                 f"Not declared, under the exemption of {CLAUSE_MODULES}"])
            add(["Integrated with other products", d["exempt"]["integrated"]])
            add(["Not identifiable at end of life",
                 d["exempt"]["not_identifiable"]])
            add(["End of life scenarios", d["exempt"]["eol_scenarios"]])
        if self.check_state == "skipped":
            add(["Model check", f"Skipped on {self.check_date}: "
                                f"{self.check_reason}"])
        else:
            add(["Model check", f"Passed on {self.check_date} (structure "
                                f"and declarations only)"])
        add(["Totals", "A1-A3 is the only total. Module D is reported on "
                       "its own and is not part of any total."])
        if self.dq:
            add([f"Share of primary data ({self.dq['indicator']}, A1-A3)",
                 self.dq["primary_share_text"]])
            add(["Programme statement",
                 f"The EPD has to carry the programme's statement on how "
                 f"the share of primary data is calculated "
                 f"({p.clause('primary_share_statement')})."])

        add([])
        add(["Cut-offs declared"])
        if d["cutoffs"]:
            add(["Module", "Item", "Share (%)"])
            for c in d["cutoffs"]:
                add([c["module"], c["item"], c["percent"]])
        else:
            add(["None declared"])

        add([])
        add(["Electricity in processes under direct control"])
        if electricity:
            unit = self.units.get(self.gwp_indicator, "") or "kg CO2 eq."
            add(["Bridge", "Modelling approach", "Energy source", "Country",
                 "Region", f"{self.gwp_indicator or 'GWP-GHG'} "
                           f"({unit} per kWh)"])
            for e in electricity:
                add([e["bridge"], e["approach"], e["energy_source"],
                     e["country"], e["region"],
                     "" if e["gwp_per_kwh"] is None else e["gwp_per_kwh"]])
        else:
            add(["No electricity bridge is used by a process under direct "
                 "control"])

        if "D" in d["modules"]:
            add([])
            add(["Module D: net flows"])
            nets = self._net_flows()
            if nets:
                add(["Flow", "Net amount", "Unit", "Quality factor (%)"])
                for n in nets:
                    add([n["flow"], n["amount"], n["unit"],
                         "Not stated" if n["quality"] is None else n["quality"]])
            else:
                add(["None declared"])

        if self.dq:
            add([])
            add([f"Data sources: processes above "
                 f"{p.gwp_row_threshold_pct:g}% of {self.dq['indicator']} "
                 f"in A1-A3"])
            add(["Process", "Modules", "Source type", "Source",
                 "Reference year", "Data category",
                 "Share of result (%)", "Share from primary data (%)"])
            for r in self.dq["rows"]:
                add([r["process"], " ".join(r["modules"]), r["source_type"],
                     r["source"], r["year"] or "", r["category"].lower(),
                     round(r["share_of_gwp"], 2), round(r["primary_share"], 2)])
            o = self.dq["others"]
            if o["count"]:
                add([f"Other processes ({o['count']})", "", "", "", "", "",
                     round(o["share"], 2), round(o["primary"], 2)])
            add(["Total share of primary data", "", "", "", "", "", "",
                 self.dq["primary_share_text"]])
            add([])
            add([f"Data quality assessment: processes that give "
                 f"{p.coverage_pct:g}% of each indicator (modules A to C)"])
            add(["Process", "Indicators it is needed for"])
            for c in self.dq["coverage"]:
                add([c["process"], c["indicators"]])

        add([])
        add(["Results (market-based electricity)" if second is not None
             else "Results"])
        add(["Indicator", "Unit"] + self._columns())
        rows.extend(self._table_rows(self.results))
        if second is not None:
            add([])
            add(["Location-based results (consumption mixes for all "
                 "electricity)"])
            add(["Indicator", "Unit"] + self._columns())
            rows.extend(self._table_rows(second))

        try:
            # newline="" stops Windows writing blank rows between lines
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(rows)
        except OSError as e:
            raise BasicError(f"Could not write '{filename}': {e}", line)
        self.reported = True
        self.out.write(f"  EPD report saved to {filename}")
        self.out.write(f"  {len(self.categories)} indicators, modules "
                       f"{', '.join(self._columns())}.")
        self.i._emit("epd_report", {
            "file": filename, "epd": d["name"], "type": d["type"],
            "modules": self.results,
            "A1-A3": self._stage_total(self.results),
            "electricity": electricity,
            "location_based": second})

    # ── EPD SAVE ─────────────────────────────────────────────

    RESULTS_FOLDER = "Results"

    def save(self, line: int, replace: bool = False,
             options: Optional[Dict] = None):
        """Write the EPD into openLCA: one stored Result per declared
        module and the Epd entity that points at them."""
        if not self.reported:
            why = ("EPD REPORT has not been run" if not self.results
                   else "EPD REPORT has not passed since the results were "
                        "last calculated")
            raise BasicError(
                f"EPD SAVE refused: {why}.", line,
                hint='Run EPD REPORT "file.csv" first. EPD SAVE stores '
                     'what the report declares, so the report has to '
                     'pass.')
        d = self.d
        systems = self._require_systems(line, "EPD SAVE")
        found = self.bridge.resolve_one("EPD", d["name"])
        if "id" in found and not replace:
            raise BasicError(
                f"An EPD called '{d['name']}' is in the database already.",
                line, hint="EPD SAVE REPLACE writes over it and over its "
                           "stored results.")
        if "id" not in found and not found.get("not_found"):
            raise BasicError(found["error"], line,
                             hint=found.get("hint", ""))
        folder = f"{self.folder}/{self.RESULTS_FOLDER}"
        modules = []
        for code, system in systems.items():
            self.i._require_valid(system["name"], line, "EPD SAVE")
            self.out.write(f"  Storing the result of {code}: "
                           f"{system['name']}...")
            opened = self.bridge.open_result(system["name"], d["method"],
                                             temporary=True)
            if "error" in opened:
                raise BasicError(f"Module {code}: {opened['error']}", line)
            try:
                got = {i["category"]: i["amount"]
                       for i in opened["impacts"]}
                for cat, want in self.results[code].items():
                    have = got.get(cat)
                    scale = max(abs(want), abs(have or 0.0), 1e-300)
                    if have is None or abs(have - want) / scale > 1e-9:
                        raise BasicError(
                            f"Module {code}: '{cat}' is now "
                            f"{_fmt(have or 0.0)}, but EPD CALCULATE and "
                            f"the report gave {_fmt(want)}. The model has "
                            f"changed since.", line,
                            hint="Run EPD CHECK, EPD CALCULATE and EPD "
                                 "REPORT again, then EPD SAVE.")
                name = f"{d['name']} | {code}"
                saved = self.bridge.save_result(
                    opened["handle"], name, folder,
                    description=f"Module {code} of the EPD '{d['name']}', "
                                f"per {d['unit_amount']:g} {d['unit']}. "
                                f"Stored by olcaBASIC EPD SAVE on "
                                f"{self.today().strftime('%d/%m/%Y')}.",
                    replace=True)
                if "error" in saved:
                    raise BasicError(f"Module {code}: {saved['error']}",
                                     line)
            finally:
                self.bridge.close_result(opened["handle"])
            modules.append({"name": code, "result_id": saved["id"],
                            "result": name})
        product_module = next((c for c in ("A3", "A1") if c in systems),
                              next(iter(systems)))
        product = next(m for m in modules if m["name"] == product_module)
        fields = dict(options or {})
        if "description" not in fields:
            fields["description"] = (
                f"{d['type']}. {d['unit_kind'].capitalize()} unit: "
                f"{d['unit_amount']:g} {d['unit']}. Method: {d['method']}. "
                f"Modules: {', '.join(d['modules'])}. "
                + (f"Programme: {self.profile.title} (GPI {d['gpi']}). "
                   if self.profile is not None else "")
                + (f"PCR: {d['pcr']} {d['pcr_version']}. ".replace(" .", ".")
                   if d["pcr"] else "")
                + f"Written by olcaBASIC EPD SAVE on "
                  f"{self.today().strftime('%d/%m/%Y')}.")
        result = self.bridge.save_epd(
            d["name"], self.folder, modules, product["result_id"],
            d["unit_amount"], d["unit"], fields, replace=replace)
        if "error" in result:
            raise BasicError(result["error"], line,
                             hint=result.get("hint") or "")
        self.i._emit("epd_save", dict(result, results=modules,
                                      folder=self.folder))
        verb = "replaced" if result.get("replaced") else "saved"
        self.out.write(
            f"  EPD {verb} in openLCA: {d['name']} ({len(modules)} modules, "
            f"product flow '{result['product']}', "
            f"{d['unit_amount']:g} {d['unit']})")
        self.out.write(f"  Stored results are in {folder}. SHOW EPD "
                       f"\"{d['name']}\" shows it.")
        self.bridge.refresh_caches()

    def _net_flows(self) -> List[Dict]:
        state = self.modules.get("D", {})
        if state.get("net_flows"):
            return state["net_flows"]
        total = self._total_of("D")
        out = []
        if total:
            tags = self._tags(total["id"])
            for key in sorted(k for k in tags if k.startswith("netflow")):
                flow, amount, unit, quality = (tags[key].split("|") + [""] * 4)[:4]
                out.append({"flow": flow, "amount": float(amount or 0),
                            "unit": unit,
                            "quality": float(quality) if quality else None})
        return out

    # ── EPD STATUS ───────────────────────────────────────────

    def status(self):
        d = self.d
        out = self.out
        out.write(f"  EPD: {d['name']} ({d['type']})")
        out.write(f"  {d['unit_kind'].capitalize()} unit: "
                  f"{d['unit_amount']:g} {d['unit']}; method: {d['method']}")
        out.write("  Programme: " + (f"{self.profile.title} (GPI {d['gpi']})"
                                     if self.profile else "none named"))
        for code in d["modules"]:
            total = self._total_of(code)
            system = self._system_of(code) if total else None
            out.write(f"    {code:<3} total: "
                      f"{total['name'] if total else 'not built':<40} "
                      f"system: {'yes' if system else 'no'}")
        steps = [
            ("EPD CHECK", self.check_state or "not run"),
            ("EPD CALCULATE", "done" if self.results else "not run"),
        ]
        if self.profile is not None:
            steps.append(("EPD DATA QUALITY",
                          "not run" if self.dq is None else
                          ("passed" if self.dq["passed"] else "failed")))
        steps.append(("EPD REPORT", "passed" if self.reported else "not run"))
        for label, state in steps:
            out.write(f"  {label}: {state}")
