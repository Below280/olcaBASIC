"""
EPD DOCUMENT: the EPD itself, as a Markdown document, in the sections
and order the programme's General Programme Instructions set out
(GPI 5.1.0, section 7.4).

What the model knows is filled in from the model: the product, the
declared unit, the EPD type, the modules, the results (two significant
digits, section 7.2), the data sources and the share of primary data,
the data quality ratings, the electricity, the cut-offs, the biogenic
carbon content, module D's net flows and the method. What only the EPD
owner knows (the owner, the product description, the content
declaration, the geography of each module, the scenarios) is given in
the EPD DOCUMENT block, and the command refuses to write a document
that leaves out something the programme requires.

The statements the programme requires word for word are not part of
olcaBASIC (no programme text is reproduced here). They are read from a
file the user keeps, named with STATEMENTS. Until that file, the
registration number, the verification details and the dates are all
given, the document is written as a draft and says what is missing.
"""

import datetime
import os
import re
from typing import Dict, List, Optional, Tuple

from ..errors import BasicError
from . import en15804

MASS_UNITS = {"kg": 1.0, "g": 0.001, "t": 1000.0}
AREA_UNITS = {"m2", "m²", "sqm"}
VOLUME_UNITS = {"m3", "m³", "l", "litre", "liter"}
LENGTH_UNITS = {"m", "km", "cm", "mm"}

MODULE_TITLES = {
    "A1": "Raw material supply", "A2": "Transport", "A3": "Manufacturing",
    "A4": "Transport", "A5": "Construction and installation",
    "B1": "Use", "B2": "Maintenance", "B3": "Repair", "B4": "Replacement",
    "B5": "Refurbishment", "B6": "Operational energy use",
    "B7": "Operational water use", "C1": "De-construction and demolition",
    "C2": "Transport", "C3": "Waste processing", "C4": "Disposal",
    "D": "Reuse, recovery and recycling potential",
}
ALL_MODULES = list(MODULE_TITLES)
DOWNSTREAM = [m for m in ALL_MODULES if m not in ("A1", "A2", "A3")]

# Words used in every IES EPD, with what they stand for
STANDARD_ABBREVIATIONS = {
    "EPD": "Environmental Product Declaration",
    "GPI": "General Programme Instructions",
    "LCA": "Life cycle assessment",
    "PCR": "Product category rules",
    "ND": "Not declared",
}

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def sig(value: float, digits: int = 2) -> str:
    """A result with a fixed number of significant digits, in the
    scientific notation of GPI section 7.2 (1.2E+2, 1.2E-2)."""
    if value == 0:
        return "0"
    mantissa, exponent = f"{value:.{digits - 1}E}".split("E")
    return f"{mantissa}E{int(exponent):+d}"


def cell(text) -> str:
    return str(text).replace("|", "/").replace("\n", " ").strip()


def read_statements(path: str) -> Dict[str, str]:
    """A statements file: 'key: text' lines; a line that starts with a
    space or a tab carries on the one before; # starts a comment."""
    out: Dict[str, str] = {}
    key = None
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            if raw[0] in " \t" and key:
                out[key] = (out[key] + " " + raw.strip()).strip()
                continue
            if ":" not in raw:
                raise ValueError(f"'{raw.strip()}' has no 'key:' in front")
            key, text = raw.split(":", 1)
            key = key.strip().lower()
            out[key] = text.strip()
    return out


class DocumentMixin:
    """EPD DOCUMENT, for EpdWorkflow."""

    def document(self, line: int, filename: str, lines: List[Dict]):
        p = self.profile
        d = self.d
        if p is None or p.name != "IES":
            raise BasicError(
                "EPD DOCUMENT writes the EPD in the format of the "
                "International EPD System, and this EPD names no "
                "programme, or another one.", line,
                hint='Add PROGRAMME "IES" GPI "5.1.0" to the EPD block.')
        if not self.reported:
            why = ("EPD REPORT has not been run" if not self.results
                   else "EPD REPORT has not passed since the results were "
                        "last calculated")
            raise BasicError(
                f"EPD DOCUMENT refused: {why}.", line,
                hint='Run EPD REPORT "file.csv" first: the document '
                     'declares what the report declares.')
        if not filename.strip():
            raise BasicError("EPD DOCUMENT needs a file name.", line,
                             hint='For example: EPD DOCUMENT "epd.md"')

        g = self._gather(lines)
        errors, draft = self._document_checks(g, line)
        if errors:
            listing = "\n".join(f"    {e}" for e in errors)
            raise BasicError(
                f"EPD DOCUMENT refused: the programme requires what is "
                f"missing or wrong here ({p.clause('document')}):\n"
                f"{listing}", line,
                hint="Add the lines to the EPD DOCUMENT block. HELP EPD "
                     "DOCUMENT shows each one. Nothing was written.")

        statements, missing = self._statements(g, line)
        draft.extend(f"the statement '{k}' ({p.statement_keys[k]})"
                     for k in missing)

        register = self._remember_register(self._dq_analyse(line))
        text = self._render(g, statements, register, draft)
        try:
            with open(filename, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except OSError as e:
            raise BasicError(f"Could not write '{filename}': {e}", line)
        self.out.write(f"  EPD document saved to {filename}")
        if draft:
            self.out.write(
                f"  It is a DRAFT: {len(draft)} item"
                f"{'s' if len(draft) != 1 else ''} the published EPD needs "
                f"{'are' if len(draft) != 1 else 'is'} still missing:")
            for item in draft:
                self.out.write(f"    {item}")
        else:
            self.out.write("  Every section the programme requires is "
                           "filled in. The document still has to be "
                           "verified before it is published.")
        self.i._emit("epd_document", {"file": filename, "epd": d["name"],
                                      "draft": bool(draft),
                                      "missing": draft})

    # ── what the block says ──────────────────────────────────

    @staticmethod
    def _gather(lines: List[Dict]) -> Dict:
        g: Dict = {}
        for e in lines:
            g.setdefault(e["key"], []).append(e)
        return g

    @staticmethod
    def _one(g: Dict, key: str, n: int = 0):
        rows = g.get(key)
        return rows[0]["args"][n] if rows else None

    def _modules_covered(self, g: Dict, key: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for e in g.get(key, []):
            for m in e["modules"]:
                out[m] = e["args"][0]
        return out

    def _document_checks(self, g: Dict, line: int) -> Tuple[List[str],
                                                            List[str]]:
        d = self.d
        p = self.profile
        errors: List[str] = []
        draft: List[str] = []

        for key in ("OWNER", "OWNER ADDRESS", "OWNER CONTACT",
                    "OWNER DESCRIPTION", "STATEMENTS", "PRACTITIONER",
                    "PRODUCT DESCRIPTION", "PRODUCT IDENTIFICATION",
                    "MANUFACTURING", "LIFESPAN", "MASS PER UNIT",
                    "AREA DENSITY", "THICKNESS", "LINEAR DENSITY", "DENSITY",
                    "RSL", "DIAGRAM", "IMAGE", "LOGO", "SOFTWARE",
                    "METHOD VERSION", "INFRASTRUCTURE", "VERIFICATION",
                    "VERIFIER", "APPROVED BY", "TOOL", "FOLLOW UP",
                    "REGISTRATION", "VERSION DATE", "VALID UNTIL",
                    "LICENSEE"):
            if len(g.get(key, [])) > 1:
                errors.append(f"{key} is given {len(g[key])} times (lines "
                              f"{', '.join(str(e['line']) for e in g[key])})")

        required = {
            "OWNER": "the EPD owner's name",
            "OWNER ADDRESS": "the EPD owner's address",
            "OWNER CONTACT": "the EPD owner's contact details",
            "OWNER DESCRIPTION": "a description of the EPD owner's "
                                 "organisation",
            "PRODUCT DESCRIPTION": "a description of the product, its "
                                   "technical performance and use",
            "PRODUCT IDENTIFICATION": "how the product is identified "
                                      "without ambiguity (standards, "
                                      "concessions or other means)",
            "MANUFACTURING": "a short description of the main "
                             "manufacturing processes",
            "SITE": "the production site(s), at least the city",
            "CONTENT": "the content declaration: each material with its "
                       "mass",
            "SVHC": "the substances of very high concern: SVHC NONE, or "
                    "one SVHC line for each",
        }
        for key, what in required.items():
            if not g.get(key):
                errors.append(f"{key}: {what}")

        # the declared unit and what converts it
        unit = (d["unit"] or "").lower()
        if unit not in MASS_UNITS and not g.get("MASS PER UNIT"):
            errors.append(f"MASS PER UNIT: the declared unit is "
                          f"{d['unit_amount']:g} {d['unit']}, not a mass, "
                          f"so the mass of one declared unit in kg is "
                          f"needed ({p.clause('lca_information')})")
        if unit in AREA_UNITS:
            for key in ("AREA DENSITY", "THICKNESS"):
                if not g.get(key):
                    errors.append(f"{key}: needed for a declared unit "
                                  f"of area")
        if unit in VOLUME_UNITS and not g.get("DENSITY"):
            errors.append("DENSITY: needed for a declared unit of volume "
                          "(kg/m3)")
        if unit in LENGTH_UNITS and not g.get("LINEAR DENSITY"):
            errors.append("LINEAR DENSITY: needed for a declared unit of "
                          "length (kg/m)")

        # every module: declared with a geography, or left out for a
        # reason
        declared = set(d["modules"])
        geo = self._modules_covered(g, "GEOGRAPHY")
        for m in ALL_MODULES:
            if m in declared and m not in geo:
                errors.append(f"GEOGRAPHY: module {m} is declared and has "
                              f"no geographical scope")
            if m not in declared and m in geo:
                errors.append(f"GEOGRAPHY: module {m} is not declared")
        omitted = self._modules_covered(g, "OMITTED")
        for m in ALL_MODULES:
            if m in declared:
                if m in omitted:
                    errors.append(f"OMITTED: module {m} is declared")
                continue
            if d["exempt"] and m in ("C1", "C2", "C3", "C4", "D"):
                continue           # the EXEMPT block gives the reasons
            if m not in omitted:
                errors.append(f"OMITTED: module {m} is not declared, and "
                              f"the reason it is left out is not given")
        scenarios = self._modules_covered(g, "SCENARIO")
        for m in DOWNSTREAM:
            if m in declared and m not in scenarios:
                errors.append(f"SCENARIO: module {m} is declared and its "
                              f"scenario is not described")

        # the content declaration
        names = [e["args"][0] for e in g.get("CONTENT", [])]
        for dup in sorted({n for n in names if names.count(n) > 1}):
            errors.append(f"CONTENT: '{dup}' is listed twice")
        for e in g.get("CONTENT", []):
            if e["args"][1] < 0:
                errors.append(f"CONTENT '{e['args'][0]}' (line {e['line']}) "
                              f"has a negative mass")
            for word, value in e["options"].items():
                if not 0 <= value <= 100:
                    errors.append(f"CONTENT '{e['args'][0]}' (line "
                                  f"{e['line']}): {word} is a share from "
                                  f"0 to 100%")
            if d["biogenic"] and "BIOGENIC" not in e["options"]:
                errors.append(
                    f"CONTENT '{e['args'][0]}' (line {e['line']}): the "
                    f"product has biogenic carbon, so each material says "
                    f"its biogenic share, BIOGENIC n% "
                    f"({p.clause('content')})")
        svhc = g.get("SVHC", [])
        if any(e["args"] == ["NONE"] for e in svhc) and len(svhc) > 1:
            errors.append("SVHC: NONE and a list of substances are both "
                          "given")
        for e in svhc:
            if e["args"] != ["NONE"] and e["args"][3] <= p.svhc_declare_pct:
                errors.append(
                    f"SVHC '{e['args'][0]}' (line {e['line']}) is at "
                    f"{e['args'][3]:g}%, not above {p.svhc_declare_pct:g}%: "
                    f"only substances above it are declared as such")

        # dates
        for key in ("VERSION DATE", "VALID UNTIL"):
            value = self._one(g, key)
            if value is not None and not DATE.match(str(value)):
                errors.append(f"{key} '{value}' is written YYYY-MM-DD "
                              f"({p.clause('units')})")
        for e in g.get("HISTORY", []):
            if not DATE.match(str(e["args"][0])):
                errors.append(f"HISTORY on line {e['line']}: the date "
                              f"'{e['args'][0]}' is written YYYY-MM-DD")
        start, end = self._one(g, "VERSION DATE"), self._one(g, "VALID UNTIL")
        if start and end and DATE.match(str(start)) and DATE.match(str(end)) \
                and end <= start:
            errors.append("VALID UNTIL is not after VERSION DATE")

        for key in ("STATEMENTS", "DIAGRAM", "IMAGE", "LOGO"):
            path = self._one(g, key)
            if path and not os.path.exists(path):
                errors.append(f"{key}: the file '{path}' does not exist")

        # what a draft may leave out
        for key, what in (
                ("REGISTRATION", "the registration number from the "
                                 "programme operator"),
                ("VERSION DATE", "the version date"),
                ("VALID UNTIL", "the validity date"),
                ("VERIFICATION", "how the EPD was verified"),
                ("VERIFIER", "the third-party verifier"),
                ("APPROVED BY", "who approved or accredited the verifier"),
                ("FOLLOW UP", "whether the verifier takes part in the "
                              "yearly follow-up (FOLLOW UP YES or NO)"),
                ("SOFTWARE", "the name and version of the LCA software"),
                ("METHOD VERSION", "the version of the EN 15804 reference "
                                   "package of the method"),
                ("DIAGRAM", "the process flow diagram"),
                ("IMAGE", "a picture of the product"),
                ("LOGO", "the EPD owner's logo"),
                ("STATEMENTS", "the programme's statements (a file you "
                               "keep: STATEMENTS \"file.txt\")")):
            if not g.get(key):
                draft.append(f"{key}: {what}")
        return errors, draft

    def _statements(self, g: Dict, line: int) -> Tuple[Dict[str, str],
                                                       List[str]]:
        p = self.profile
        path = self._one(g, "STATEMENTS")
        found: Dict[str, str] = {}
        if path:
            try:
                found = read_statements(path)
            except (OSError, ValueError) as e:
                raise BasicError(f"Could not read the statements in "
                                 f"'{path}': {e}", line,
                                 hint="Each line is 'key: text'.")
        needed = [k for k in p.statement_keys
                  if k != "end_of_life" or any(
                      m in self.d["modules"] for m in ("C1", "C2", "C3",
                                                       "C4"))]
        missing = [k for k in needed if not found.get(k)] if path else []
        return found, missing

    def _say(self, statements: Dict[str, str], key: str) -> str:
        text = statements.get(key)
        if text:
            return text
        return (f"[DRAFT: the statement '{key}' required by GPI "
                f"{self.profile.gpi_versions[-1]}, "
                f"{self.profile.statement_keys[key]}, goes here]")

    # ── the document ─────────────────────────────────────────

    def _render(self, g: Dict, statements: Dict[str, str],
                register: List[Dict], draft: List[str]) -> str:
        from .. import __version__
        d = self.d
        p = self.profile
        one = lambda key, n=0: self._one(g, key, n)  # noqa: E731
        out: List[str] = []
        add = out.append

        def blank():
            if out and out[-1] != "":
                add("")

        def heading(level: int, text: str):
            blank()
            add("#" * level + " " + text)
            add("")

        def table(head: List[str], rows: List[List]):
            blank()
            add("| " + " | ".join(cell(h) for h in head) + " |")
            add("|" + "---|" * len(head))
            for r in rows:
                add("| " + " | ".join(cell(x) for x in r) + " |")
            add("")

        if draft:
            add("> **DRAFT, not for publication.** Missing: "
                + "; ".join(draft) + ".")
            add("")

        # cover page (7.4.1)
        add(f"# Environmental Product Declaration: {d['name']}")
        add("")
        if one("LOGO"):
            add(f"![Logo of {one('OWNER')}]({one('LOGO')})")
            add("")
        if one("IMAGE"):
            add(f"![{d['name']}]({one('IMAGE')})")
            add("")
        cover = [["Product", d["name"]],
                 ["EPD owner", one("OWNER")],
                 ["Programme", f"{p.programme_title}, "
                               f"{p.programme_website}"],
                 ["Programme operator", p.operator_name]]
        if one("LICENSEE"):
            cover.append(["Licensee", one("LICENSEE")])
        cover += [["EPD registration number",
                   one("REGISTRATION") or "[DRAFT: not registered yet]"],
                  ["Version date", one("VERSION DATE") or "[DRAFT]"],
                  ["Validity date", one("VALID UNTIL") or "[DRAFT]"]]
        table(["", ""], cover)
        add(self._say(statements, "cover"))
        add("")
        add(self._say(statements, "iso14025"))

        # general information (7.4.2)
        heading(2, "General information")
        heading(3, "Programme information")
        table(["", ""], [["Programme", p.programme_title],
                         ["Programme operator", p.operator_name],
                         ["Address", self._say(statements, "operator")],
                         ["Website", p.programme_website]])
        heading(3, "Product category rules (PCR)")
        pcr = " ".join(x for x in (d["pcr"], d["pcr_version"]) if x)
        table(["", ""], [
            ["Core PCR", "CEN standard EN 15804 serves as the core PCR"],
            ["PCR", pcr or "[not named in the EPD block: add PCR \"name\" "
                           "VERSION \"n\"]"]])
        heading(3, "Verification")
        rows = [["Verification", one("VERIFICATION") or "[DRAFT]"],
                ["Third-party verifier", one("VERIFIER") or "[DRAFT]"],
                ["Approved or accredited by",
                 one("APPROVED BY") or "[DRAFT]"]]
        if one("TOOL"):
            rows.append(["Pre-verified tool", one("TOOL")])
        follow = one("FOLLOW UP")
        rows.append(["Follow-up of data during validity involves the "
                     "verifier", "[DRAFT]" if follow is None
                     else ("Yes" if follow else "No")])
        table(["", ""], rows)
        heading(3, "Ownership and limitations on use of the EPD")
        add(self._say(statements, "ownership"))
        add("")
        add(self._say(statements, "comparability"))

        # EPD owner (7.4.3)
        heading(2, "Information about the EPD owner")
        table(["", ""], [["EPD owner", one("OWNER")],
                         ["Address", one("OWNER ADDRESS")],
                         ["Contact", one("OWNER CONTACT")]]
              + ([["LCA practitioner", one("PRACTITIONER")]]
                 if one("PRACTITIONER") else []))
        add(one("OWNER DESCRIPTION"))

        # product (7.4.4)
        heading(2, "Product information")
        rows = [["Product name", d["name"]],
                ["Identification", one("PRODUCT IDENTIFICATION")]]
        for e in g.get("PRODUCT CODE", []):
            rows.append([f"{e['args'][0]} code",
                         f"{e['args'][1]}: {e['args'][2]}"])
        rows.append(["Production site" + ("s" if len(g["SITE"]) > 1
                                          else ""),
                     "; ".join(e["args"][0] for e in g["SITE"])])
        if one("LIFESPAN"):
            rows.append(["Technical or actual lifespan", one("LIFESPAN")])
        for e in g.get("WEBSITE", []):
            rows.append(["More information", e["args"][0]])
        table(["", ""], rows)
        add(one("PRODUCT DESCRIPTION"))
        add("")
        add(f"**Manufacturing.** {one('MANUFACTURING')}")

        # content declaration (7.4.5)
        heading(2, "Content declaration")
        self._content_tables(g, table, add)

        # LCA information (7.4.6)
        heading(2, "LCA information")
        rows = [[f"{d['unit_kind'].capitalize()} unit",
                 f"{d['unit_amount']:g} {d['unit']}"]]
        unit = (d["unit"] or "").lower()
        if one("MASS PER UNIT") is not None:
            rows.append(["Conversion factor to mass",
                         f"{one('MASS PER UNIT'):g} kg per {d['unit']}"])
        for key, label, u in (("AREA DENSITY", "Area density", "kg/m2"),
                              ("THICKNESS", "Thickness", "m"),
                              ("DENSITY", "Density", "kg/m3"),
                              ("LINEAR DENSITY", "Linear density", "kg/m")):
            if one(key) is not None:
                rows.append([label, f"{one(key):g} {u}"])
        if one("RSL"):
            rows.append(["Reference service life", one("RSL")])
        rows.append(["System boundary", d["type"]])
        rows.append(["LCA software", one("SOFTWARE") or "[DRAFT]"])
        rows.append(["Calculated with", f"olcaBASIC {__version__}"])
        rows.append(["Background database",
                     " ".join(x for x in (d["database"],
                                          d["database_version"]) if x)
                     or "Not stated in the EPD block"])
        if one("INFRASTRUCTURE"):
            rows.append(["Infrastructure and capital goods",
                         one("INFRASTRUCTURE")])
        table(["", ""], rows)

        heading(3, "Modules declared and geographical scope")
        geo = self._modules_covered(g, "GEOGRAPHY")
        declared = set(d["modules"])
        table(["Module"] + ALL_MODULES,
              [["Declared"] + ["X" if m in declared else "ND"
                               for m in ALL_MODULES],
               ["Geography"] + [geo.get(m, "") if m in declared else ""
                                for m in ALL_MODULES]])
        omitted = self._modules_covered(g, "OMITTED")
        reasons = []
        for reason in dict.fromkeys(omitted.values()):
            mods = [m for m in ALL_MODULES if omitted.get(m) == reason]
            reasons.append([", ".join(mods), reason])
        if d["exempt"]:
            e = d["exempt"]
            reasons.append(["C1-C4, D", f"Not declared under the exemption "
                                        f"of EN 15804+A2, 5.2: "
                                        f"{e['integrated']}; "
                                        f"{e['not_identifiable']}; "
                                        f"{e['eol_scenarios']}"])
        if reasons:
            heading(3, "Life-cycle stages not considered")
            table(["Modules", "Why they are left out"], reasons)

        heading(3, "Process flow diagram")
        if one("DIAGRAM"):
            add(f"![Process flow diagram]({one('DIAGRAM')})")
        else:
            add("[DRAFT: the process flow diagram goes here, divided into "
                "life-cycle stages and modules, with the system boundary.]")

        scen = self._modules_covered(g, "SCENARIO")
        if scen:
            heading(3, "Scenarios")
            rows = []
            for text in dict.fromkeys(scen.values()):
                mods = [m for m in ALL_MODULES if scen.get(m) == text]
                rows.append([", ".join(mods), text])
            table(["Modules", "Scenario"], rows)

        self._data_sections(statements, register, table, add, heading)
        self._method_section(g, table, heading)

        # environmental performance (7.4.7)
        heading(2, "Environmental performance")
        self._result_tables(table, heading)
        add(self._say(statements, "relative"))
        if any(m in declared for m in ("C1", "C2", "C3", "C4")):
            add("")
            add(self._say(statements, "end_of_life"))
        if "D" in declared:
            add("")
            add("Module D is declared on its own and is not added to any "
                "total.")

        extra = g.get("ADDITIONAL", [])
        if extra:
            heading(2, "Additional environmental information")
            for e in extra:
                add(e["args"][0])
                add("")

        # version history, abbreviations, references (7.4.11 to 7.4.13)
        heading(2, "Version history")
        history = [[e["args"][0], e["args"][1]] for e in g.get("HISTORY", [])]
        if not history:
            history = [[one("VERSION DATE") or "[DRAFT]",
                        "Original version of the EPD"]]
        table(["Date", "Change"], history)

        heading(2, "Abbreviations")
        abbreviations = dict(STANDARD_ABBREVIATIONS)
        for c in self.categories:
            code = en15804.indicator_code(c["name"])
            if code and code not in abbreviations:
                abbreviations[code] = self._plain_name(c["name"])
        for e in g.get("ABBREVIATION", []):
            abbreviations[e["args"][0]] = e["args"][1]
        table(["Abbreviation", "Meaning"],
              [[k, abbreviations[k]] for k in sorted(abbreviations,
                                                     key=str.lower)])

        heading(2, "References")
        refs = [f"{p.title}: {p.document}, version {d['gpi']}.",
                "EN 15804:2012+A2:2019, Sustainability of construction "
                "works. Environmental product declarations. Core rules for "
                "the product category of construction products.",
                "ISO 14025:2006, Environmental labels and declarations. "
                "Type III environmental declarations. Principles and "
                "procedures."]
        if pcr:
            refs.append(f"PCR: {pcr}.")
        if d["database"]:
            refs.append(f"Background data: "
                        f"{' '.join(x for x in (d['database'], d['database_version']) if x)}.")
        refs.extend(e["args"][0] for e in g.get("REFERENCE", []))
        for r in refs:
            add(f"- {r}")
        add("")
        return "\n".join(out).rstrip() + "\n"

    @staticmethod
    def _plain_name(name: str) -> str:
        """'01 Core - Global Warming Potential - total (GWP-total) -
        v3.1' -> 'Global Warming Potential - total'"""
        text = re.sub(r"^\d+\s+\w+\s+-\s+", "", name)
        text = re.sub(r"\s*-\s*v\d+(\.\d+)*\s*$", "", text)
        text = re.sub(r"\s*\([^()]*\)\s*$", "", text)
        return text.strip()

    def _content_tables(self, g: Dict, table, add):
        d = self.d
        p = self.profile
        product_kg = sum(e["args"][1] * MASS_UNITS[e["unit"]]
                         for e in g["CONTENT"])
        rows = []
        for e in g["CONTENT"]:
            kg = e["args"][1] * MASS_UNITS[e["unit"]]
            o = e["options"]
            rows.append([e["args"][0], f"{kg:g}",
                         f"{o['RECYCLED']:g}" if "RECYCLED" in o else "0",
                         f"{o['PRECONSUMER']:g}" if "PRECONSUMER" in o
                         else "0",
                         f"{o['BIOGENIC']:g}" if "BIOGENIC" in o else "0"])
        biogenic_kg_c = (d["biogenic_content"]["product"]
                         if d["biogenic"] else 0.0)
        rows.append(["Total", f"{product_kg:g}", "", "", "",
                     ])
        table(["Product content", "Mass, kg",
               "Post-consumer recycled material, mass-% of product",
               "Pre-consumer recycled material, mass-% of product",
               "Biogenic material, mass-% of product"], rows)
        add(f"Mass of one declared unit: {product_kg:g} kg. Biogenic "
            f"carbon content of the product: {biogenic_kg_c:g} kg C per "
            f"declared unit (1 kg of biogenic carbon is equivalent to "
            f"44/12 kg of CO2 taken up).")
        add("")
        packaging = g.get("PACKAGING", [])
        if packaging:
            pack_c = (d["biogenic_content"]["packaging"]
                      if d["biogenic"] else 0.0)
            prow = []
            total = 0.0
            for e in packaging:
                kg = e["args"][1] * MASS_UNITS[e["unit"]]
                total += kg
                share = kg / product_kg * 100 if product_kg else 0.0
                prow.append([e["args"][0], f"{kg:g}", f"{share:.2g}"])
            prow.append(["Total", f"{total:g}",
                         f"{total / product_kg * 100:.2g}" if product_kg
                         else "0"])
            table(["Packaging materials", "Mass, kg",
                   "Mass-% (versus the product)"], prow)
            add(f"Biogenic carbon content of the packaging: {pack_c:g} kg "
                f"C per declared unit.")
            add("")
        svhc = g["SVHC"]
        if svhc[0]["args"] == ["NONE"]:
            add(f"The product contains no substance on the Candidate List "
                f"of Substances of Very High Concern above "
                f"{p.svhc_declare_pct:g}% of its mass.")
        else:
            table(["Substance of very high concern", "EC No.", "CAS No.",
                   "Mass-% per declared unit"],
                  [[e["args"][0], e["args"][1], e["args"][2],
                    f"{e['args'][3]:g}"] for e in svhc])

    def _data_sections(self, statements, register, table, add, heading):
        p = self.profile
        dq = self.dq or {}
        heading(3, "Data sources and share of primary data")
        if dq.get("rows"):
            rows = [[r["process"], " ".join(r["modules"]), r["source_type"],
                     r["source"], r["year"] or "", r["category"].lower(),
                     f"{r['share_of_gwp']:.2g}", f"{r['primary_share']:.2g}"]
                    for r in dq["rows"]]
            others = dq.get("others") or {}
            if others.get("count"):
                rows.append([f"Other processes ({others['count']})", "", "",
                             "", "", "", f"{others['share']:.2g}",
                             f"{others['primary']:.2g}"])
            table(["Process", "Modules", "Source type", "Source",
                   "Reference year", "Data category",
                   f"Share of {dq.get('indicator', 'GWP-GHG')} in A1-A3 (%)",
                   "Share from primary data (%)"], rows)
        add(f"Share of primary data ({dq.get('indicator', 'GWP-GHG')}, "
            f"A1-A3): {dq.get('primary_share_text', 'not calculated')}.")
        add("")
        add(self._say(statements, "primary_share"))

        heading(3, "Data quality")
        needed = [r for r in register if r["needed_for"]]
        rows = []
        for r in needed:
            name = r["dataset"] + (f" (background: {r['background']})"
                                   if r["background"] else "")
            cells = []
            for aspect in en15804.DQ_ASPECTS:
                rating = r["ratings"].get(aspect)
                cells.append(f"{rating['level']}: {rating['reason']}"
                             if rating else "Not rated")
            rows.append([name] + cells)
        add(f"The data quality assessment covers the data that together "
            f"give at least {p.coverage_pct:g}% of each declared "
            f"environmental impact indicator, rated on the scale of "
            f"{p.dq_scheme}.")
        if rows:
            table(["Dataset"] + [en15804.DQ_ASPECT_TITLES[a]
                                 for a in en15804.DQ_ASPECTS], rows)

        cut = self.d["cutoffs"]
        if cut:
            heading(3, "Cut-offs")
            table(["Module", "What was left out", "Share (%)"],
                  [[c["module"], c["item"], f"{c['percent']:g}"]
                   for c in cut])

        electricity = self._electricity_rows(0)
        if electricity:
            heading(3, "Electricity")
            unit = self.units.get(self.gwp_indicator, "") or "kg CO2 eq."
            table(["Electricity", "Modelling approach", "Energy source",
                   "Country", f"{self.gwp_indicator or 'GWP-GHG'} "
                              f"({unit} per kWh)"],
                  [[e["bridge"], e["approach"], e["energy_source"],
                    e["country"], "" if e["gwp_per_kwh"] is None
                    else sig(e["gwp_per_kwh"], p.result_digits)]
                   for e in electricity])

        if "D" in self.d["modules"]:
            nets = self._net_flows()
            if nets:
                heading(3, "Module D: net flows")
                table(["Flow", "Net amount", "Unit", "Quality factor (%)"],
                      [[n["flow"], sig(n["amount"], p.result_digits),
                        n["unit"], "Not stated" if n["quality"] is None
                        else f"{n['quality']:g}"] for n in nets])

    def _method_section(self, g, table, heading):
        d = self.d
        heading(3, "Characterisation methods")
        version = self._one(g, "METHOD VERSION")
        rows = []
        for c in self.categories:
            code = en15804.indicator_code(c["name"]) or ""
            rows.append([code, self._plain_name(c["name"]), c["unit"]])
        table(["Indicator", "Name", "Unit"], rows)
        heading(4, "Method")
        table(["", ""], [["Method", d["method"]],
                         ["EN 15804 reference package",
                          version or "[DRAFT: METHOD VERSION]"]])

    def _result_tables(self, table, heading):
        p = self.profile
        cols = self._columns()
        stage = self._stage_total(self.results)
        groups: Dict[str, List] = {}
        for c in self.categories:
            m = re.match(r"^\d+\s+(.+?)\s+-\s+", c["name"])
            group = m.group(1) if m else "Results"
            row = [en15804.indicator_code(c["name"])
                   or self._plain_name(c["name"]), c["unit"]]
            for col in cols:
                value = (stage[c["name"]] if col == "A1-A3"
                         else self.results[col][c["name"]])
                row.append(sig(value, p.result_digits))
            groups.setdefault(group, []).append(row)
        unit = f"{self.d['unit_amount']:g} {self.d['unit']}"
        for group, rows in groups.items():
            heading(3, f"{group} indicators, per {unit}"
                    if group != "Results" else f"Results per {unit}")
            table(["Indicator", "Unit"] + cols, rows)
