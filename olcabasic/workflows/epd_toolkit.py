"""
The EPD toolkit: the parts of an EPD study that used to be separate
scripts.

    EPD DATA QUALITY [PARAMETER SET "name" | FROM "scenarios.csv"]
    RATING GEOGRAPHY|TECHNOLOGY|TIME "level" REASON "why"
    EPD DQ SHEET "file.csv"        EPD DQ TABLE "file.md"
    BIOGENIC CONTENT ... / BIOGENIC EXPORT ... and the carbon balances
    EPD SENSITIVITY BY n% ... END EPD SENSITIVITY
    EPD EXPORT MODEL "file.json"

Part of olcabasic.workflows.epd.EpdWorkflow. Every limit used here is
a named value of the programme profile or of en15804.py; clause
numbers only, no text of a standard or of a programme's instructions.
"""

import csv
import json
import os
from typing import Dict, List, Optional

from ..errors import BasicError
from . import en15804

RATING_KEYS = {"GEOGRAPHY": "rating_geography",
               "TECHNOLOGY": "rating_technology",
               "TIME": "rating_time"}


def encode_reason(text: str) -> str:
    """A reason as it is stored in a tag. openLCA splits tags at
    commas, so commas are written %2C (and % as %25)."""
    return (str(text).replace("%", "%25").replace(",", "%2C")
            .replace("\n", " ").strip())


def decode_reason(text: str) -> str:
    return str(text).replace("%2C", ",").replace("%25", "%")


def rating_tags(ratings: Dict, eval_str, levels, clause: str) -> Dict:
    """The tags the RATING lines of a block become. A level that is
    not on the scale is an error listing the levels."""
    tags = {}
    by_lower = {lv.lower(): lv for lv in levels}
    for aspect, r in (ratings or {}).items():
        given = " ".join(eval_str(r["level"]).split())
        level = by_lower.get(given.lower())
        if level is None:
            raise BasicError(
                f"'{given}' is not a level of the data quality scale.",
                r["line"],
                hint="The levels are " + ", ".join(f'"{lv}"' for lv in levels)
                     + f" ({clause}).")
        reason = eval_str(r["reason"]).strip()
        if not reason:
            raise BasicError(
                f"RATING {aspect} has an empty REASON.", r["line"],
                hint="Say in a sentence why the data earns that level.")
        tags[RATING_KEYS[aspect]] = level
        tags[RATING_KEYS[aspect] + "_reason"] = encode_reason(reason)
    return tags


def ratings_of(tags: Dict) -> Dict[str, Dict]:
    """{aspect: {"level", "reason"}} from a process's tags; an aspect
    without a rating is left out."""
    out = {}
    for aspect, key in RATING_KEYS.items():
        level = tags.get(key)
        if level:
            out[aspect] = {"level": level,
                           "reason": decode_reason(tags.get(key + "_reason",
                                                            ""))}
    return out


def _fmt(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 1e6 or abs(value) < 1e-3:
        return f"{value:.4e}"
    return f"{value:.6g}"


def _pct(value: float) -> str:
    return f"{value:.1f}%"


class EpdToolkitMixin:

    # ── indicators by code ───────────────────────────────────

    def _codes(self) -> Dict[str, Optional[str]]:
        """{category name: code}, the code being the one in brackets
        at the end of the name."""
        if not hasattr(self, "_code_cache"):
            self._code_cache = {c["name"]: en15804.indicator_code(c["name"])
                                for c in self.categories}
        return self._code_cache

    def category_with_code(self, code: str) -> str:
        """The name of the one category that carries a code, or ''."""
        hits = [n for n, c in self._codes().items() if c == code]
        return hits[0] if len(hits) == 1 else ""

    def _impact_categories(self, line: int) -> List[str]:
        """The method's impact indicators, in the method's order."""
        p = self.profile
        codes = self._codes()
        have = set(codes.values())
        missing = [c for c in p.required_indicator_codes if c not in have]
        if missing:
            raise BasicError(
                f"The impact indicators of '{self.d['method']}' could not "
                f"be picked out: no category name carries "
                f"{', '.join(missing)} in brackets.", line,
                hint=f"The coverage and the proxy limit run over the "
                     f"environmental impact indicators only "
                     f"({p.clause('impact_indicators')}; "
                     f"{en15804.CLAUSE_INDICATORS}). They are told from the "
                     f"resource use, waste and output flow indicators by "
                     f"the code at the end of each category name, as "
                     f"openLCA's EN 15804 method packs write it: "
                     f"'Climate change (GWP-total)'.")
        wanted = set(p.impact_indicator_codes)
        return [c["name"] for c in self.categories
                if codes[c["name"]] in wanted]

    # ── the split of each module ─────────────────────────────

    def _walk(self, code: str) -> Dict:
        """The processes of a module, from its total process down to
        its bridges: {"direct": [ids], "upstream": [ids], "unbridged":
        [names], "info": {id: {...}}}. direct: the EPD's own processes.
        upstream: the bridges. unbridged: processes outside the EPD
        folder that are used without a bridge."""
        total = self._total_of(code)
        direct, upstream, unbridged, info = [], [], [], {}
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
            if not bridged and not mine:
                unbridged.append(st["name"])
                continue
            tags = self._tags(pid)
            info[pid] = {"id": pid, "name": st["name"], "module": code,
                         "tags": tags, "is_bridge": bridged,
                         "is_total": tags.get("role") == "total"
                         or pid == total["id"]}
            if bridged:
                upstream.append(pid)
                continue
            direct.append(pid)
            stack.extend(l["provider_id"] for l in st["links"])
        return {"direct": direct, "upstream": upstream,
                "unbridged": unbridged, "info": info}

    def _parts(self, code: str, system: Dict, line: int,
               parameters: Optional[Dict] = None) -> Dict:
        """Split a module's result between the EPD's own processes
        (their direct impacts) and the bridges that feed them (their
        upstream impacts). On a model built through bridges they add
        up to the module's total; the residual check looks at that."""
        walk = self._walk(code)
        info = walk["info"]
        got = self.bridge.process_contributions(
            system["id"], self.d["method"], direct=walk["direct"],
            upstream=walk["upstream"], parameters=parameters)
        if "error" in got:
            raise BasicError(f"Module {code}: {got['error']}", line)
        parts = []
        for pid in walk["direct"]:
            if pid in got["direct"]:
                parts.append(dict(info[pid], values=got["direct"][pid]))
        for pid in walk["upstream"]:
            if pid in got["upstream"]:
                parts.append(dict(info[pid], values=got["upstream"][pid]))
        return {"totals": got["totals"], "parts": parts,
                "unbridged": walk["unbridged"]}

    def _residuals(self, split: Dict[str, Dict]) -> List[str]:
        """For every indicator and every module, the parts must add up
        to the module's total."""
        p = self.profile
        errors = []
        for code, data in split.items():
            gaps = []
            for cat, total in data["totals"].items():
                if abs(total) < p.residual_floor:
                    continue
                parts = sum(part["values"].get(cat, 0.0)
                            for part in data["parts"])
                gap = total - parts
                share = 100.0 * abs(gap) / abs(total)
                if share > p.residual_tolerance_pct:
                    gaps.append((share, cat, total, parts, gap))
            if not gaps:
                continue
            gaps.sort(reverse=True)
            share, cat, total, parts, gap = gaps[0]
            more = (f" {len(gaps) - 1} other indicator"
                    f"{'s have' if len(gaps) != 2 else ' has'} a gap too."
                    if len(gaps) > 1 else "")
            cause = ("The usual cause is an input that does not go through "
                     "a bridge.")
            if data["unbridged"]:
                names = ", ".join(f"'{n}'" for n in data["unbridged"][:5])
                cause = (f"Used without a bridge in this module: {names}. "
                         f"Put each behind a BRIDGE block.")
            errors.append(
                f"Module {code}: the module's processes and bridges add up "
                f"to {_fmt(parts)} of '{cat}', but the module total is "
                f"{_fmt(total)}: a gap of {_fmt(gap)} ({share:.2f}%, limit "
                f"{p.residual_tolerance_pct:g}%).{more} {cause}")
        return errors

    # ── EPD DATA QUALITY ─────────────────────────────────────

    def _dq_require(self, line: int, command: str):
        p = self.profile
        if p is None:
            raise BasicError(
                f"{command} applies a programme's rules, and the EPD "
                f"block names no programme.", line,
                hint='Add PROGRAMME "IES" GPI "5.1.0" to the EPD block.')
        if not self.results:
            raise BasicError(
                f"{command} needs the results.", line,
                hint="Run EPD CALCULATE first.")
        if not self.gwp_indicator:
            raise BasicError(
                f"The GWP-GHG indicator of '{self.d['method']}' could not "
                f"be picked out by its code or its name.", line,
                hint='Name it in the EPD block: GWP INDICATOR "full name of '
                     'the category".')

    def _dq_analyse(self, line: int, parameters: Optional[Dict] = None,
                    label: str = "") -> Dict:
        """The data quality analysis of the active EPD, for the model
        as it is or with parameter values redefined. Returns everything
        found; writes nothing."""
        p = self.profile
        systems = self._require_systems(line, "EPD DATA QUALITY")
        impact = self._impact_categories(line)
        gwp = self.gwp_indicator
        year_now = self.today().year
        errors: List[str] = []

        split = {}
        for code in self.d["modules"]:
            values = None
            if parameters:
                held = self._held_by(code)
                values = {n: v for n, v in parameters.items() if n in held}
            split[code] = self._parts(code, systems[code], line, values)
        errors.extend(self._residuals(split))

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
            e["year"] = (int(tags["year"])
                         if tags.get("year", "").isdigit() else None)
            share = tags.get("share")
            e["primary_share"] = (float(share) if share not in (None, "")
                                  else (100.0 if category == "PRIMARY"
                                        else 0.0))
            carries = any(magnitude(e, c["name"], e["modules"]) > 0
                          for c in self.categories)
            if e["is_total"] and not category:
                continue
            if not category:
                if carries:
                    errors.append(
                        f"'{e['name']}' has no data declaration, so its "
                        f"share cannot be placed "
                        f"({p.clause('data_quality')}).")
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
            e["gwp_share"] = share
            if share > p.gwp_row_threshold_pct:
                e["gwp_row"] = True
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
        for r in rows:
            if r["year"] is None:
                errors.append(
                    f"'{r['process']}' gives more than "
                    f"{p.gwp_row_threshold_pct:g}% of '{gwp}' in A1-A3 and "
                    f"its DATA line has no YEAR: the reference year is "
                    f"declared ({p.clause('data_quality')}).")

        # The reference year of every A3 (core) process is declared,
        # however small its share (A.5.4).
        listed = {r["process"] for r in rows}
        a3_years = []
        for e in sorted(entries.values(), key=lambda e: e["name"]):
            if "A3" not in e["modules"] or e["is_total"] \
                    or e["name"] in listed or not e.get("category"):
                continue
            if e["year"] is None:
                errors.append(
                    f"'{e['name']}' is an A3 (core) process and its DATA "
                    f"line has no YEAR: the reference year of core data is "
                    f"declared whatever its share "
                    f"({p.clause('data_quality')}).")
            a3_years.append({"process": e["name"], "year": e["year"]})

        # Processes after A3 that give more than the threshold of GWP-GHG
        # over all the stages declared: their database is declared too.
        later = [c for c in self.d["modules"]
                 if c not in p.product_stage and c != "D"]
        downstream = []
        if later:
            every = [c for c in self.d["modules"] if c != "D"]
            whole = sum(magnitude(e, gwp, every) for e in entries.values())
            for e in sorted(entries.values(),
                            key=lambda e: -magnitude(e, gwp, later)):
                amount = magnitude(e, gwp, later)
                if not whole or not amount or e["is_total"]:
                    continue
                share = 100.0 * amount / whole
                if share <= p.gwp_row_threshold_pct:
                    continue
                source = e["tags"].get("provider", "")
                if not source:
                    errors.append(
                        f"'{e['name']}' gives {_pct(share)} of '{gwp}' over "
                        f"all declared stages, in "
                        f"{', '.join(m for m in e['modules'] if m in later)}: "
                        f"its database and version are declared, and its "
                        f"DATA line names no PROVIDER "
                        f"({p.clause('data_quality')}).")
                downstream.append({
                    "process": e["name"],
                    "modules": [m for m in e["modules"] if m in later],
                    "source_type": e["tags"].get("source", ""),
                    "source": source, "share_of_gwp": share})

        # Proxy data, per impact indicator: A to C together, D on its own
        groups = [("A to C", [c for c in self.d["modules"] if c != "D"])]
        if "D" in self.d["modules"]:
            groups.append(("D", ["D"]))
        proxy = []
        for group, codes in groups:
            for cat in impact:
                whole = sum(magnitude(e, cat, codes) for e in entries.values())
                if not whole:
                    continue
                part = sum(magnitude(e, cat, codes) for e in entries.values()
                           if e["effective"] == "PROXY")
                share = 100.0 * part / whole
                if share > 0:
                    proxy.append({"modules": group, "indicator": cat,
                                  "share": share})
                if share > p.proxy_limit_pct:
                    errors.append(
                        f"Proxy data gives {_pct(share)} of '{cat}' in "
                        f"modules {group}; the limit is "
                        f"{p.proxy_limit_pct:g}% of any impact indicator "
                        f"({p.clause('proxy')}).")

        # What the data quality assessment has to cover
        codes = groups[0][1]
        needed: Dict[str, int] = {}
        for cat in impact:
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
                needed[e["id"]] = needed.get(e["id"], 0) + 1
        coverage = sorted(((entries[i], n) for i, n in needed.items()),
                          key=lambda en: (-en[1], en[0]["name"]))

        # Every dataset of that set carries its three ratings
        unrated = []
        for e, _ in coverage:
            have = ratings_of(e["tags"])
            lacking = [a for a in en15804.DQ_ASPECTS if a not in have]
            e["ratings"] = have
            if lacking:
                unrated.append(e["name"])
                errors.append(
                    f"'{e['name']}' is in the {p.coverage_pct:g}% coverage "
                    f"and has no RATING for {', '.join(lacking)} "
                    f"({p.clause('ratings')}).")
        for e in entries.values():
            e.setdefault("ratings", ratings_of(e["tags"]))

        return {
            "passed": not errors, "label": label, "indicator": gwp,
            "rows": rows, "others": others, "primary_share": primary_total,
            "a3_years": a3_years, "downstream": downstream,
            "primary_share_text": primary_text, "proxy": proxy,
            "coverage": [{"process": e["name"], "indicators": n}
                         for e, n in coverage],
            "impact_indicators": len(impact),
            "indicators_reported": len(self.categories),
            "unrated": unrated, "errors": errors,
            # for the register; not part of the structured result
            "_entries": entries, "_needed": needed,
        }

    def _dq_print(self, a: Dict):
        p = self.profile
        gwp = a["indicator"]
        out = self.out
        head = f" [{a['label']}]" if a["label"] else ""
        out.write(f"  EPD DATA QUALITY{head}: {self.name} "
                  f"({p.title}, GPI {self.d['gpi']})")
        out.write(f"  Processes above {p.gwp_row_threshold_pct:g}% of "
                  f"'{gwp}' in A1-A3:")
        out.write("    " + "Process".ljust(44) + "Source type".ljust(16)
                  + "Source".ljust(20) + "Year".ljust(6)
                  + "Category".ljust(11) + "Share".rjust(8)
                  + "Primary".rjust(9))
        for r in a["rows"]:
            out.write("    " + r["process"][:42].ljust(44)
                      + r["source_type"][:14].ljust(16)
                      + r["source"][:18].ljust(20)
                      + str(r["year"] or "").ljust(6)
                      + r["category"].lower().ljust(11)
                      + _pct(r["share_of_gwp"]).rjust(8)
                      + _pct(r["primary_share"]).rjust(9))
        others = a["others"]
        if others["count"]:
            out.write("    " + f"Other processes ({others['count']})".ljust(97)
                      + _pct(others["share"]).rjust(8)
                      + _pct(others["primary"]).rjust(9))
        out.write(f"  Share of primary data in '{gwp}', A1-A3: "
                  f"{a['primary_share_text']}")
        if a.get("a3_years"):
            out.write("  Reference years of the other A3 (core) processes:")
            for r in a["a3_years"]:
                out.write(f"    {r['process']}: {r['year'] or 'none given'}")
        if a.get("downstream"):
            out.write(f"  Processes after A3 above "
                      f"{p.gwp_row_threshold_pct:g}% of '{gwp}' over all "
                      f"declared stages:")
            for r in a["downstream"]:
                out.write(f"    {r['process']} ({' '.join(r['modules'])}): "
                          f"{r['source_type'] or 'source type not given'}, "
                          f"{r['source'] or 'no source'}, "
                          f"{_pct(r['share_of_gwp'])}")
        if a["proxy"]:
            worst = max(a["proxy"], key=lambda r: r["share"])
            out.write(f"  Proxy data: at most {_pct(worst['share'])} of an "
                      f"impact indicator ('{worst['indicator']}', modules "
                      f"{worst['modules']}); limit {p.proxy_limit_pct:g}%.")
        else:
            out.write("  Proxy data: none.")
        out.write(f"  Counted: the {a['impact_indicators']} environmental "
                  f"impact indicators of the method's "
                  f"{a['indicators_reported']} categories "
                  f"({p.clause('impact_indicators')}). Resource use, waste "
                  f"and output flow indicators are reported, not counted.")
        out.write(f"  The data quality assessment has to cover these "
                  f"({p.coverage_pct:g}% of each impact indicator, modules "
                  f"A to C):")
        for row in a["coverage"]:
            rated = "" if row["process"] not in a["unrated"] else \
                "  [not rated]"
            out.write(f"    {row['process']} (needed for "
                      f"{row['indicators']} of {a['impact_indicators']} "
                      f"impact indicators){rated}")
        out.write(f"  The EPD has to carry the programme's statement on how "
                  f"the share of primary data is calculated "
                  f"({p.clause('primary_share_statement')}).")
        for text in a["errors"]:
            out.write(f"  ERROR: {text}")

    @staticmethod
    def _public(a: Dict) -> Dict:
        return {k: v for k, v in a.items() if not k.startswith("_")}

    def data_quality(self, line: int, parameter_set: str = "",
                     from_file: str = ""):
        self._dq_require(line, "EPD DATA QUALITY")
        if parameter_set or from_file:
            return self._dq_scenarios(line, parameter_set, from_file)
        a = self._dq_analyse(line)
        self._dq_print(a)
        self.dq = self._public(a)
        self._remember_register(a)
        self.i._emit("epd_data_quality", self.dq)
        self._dq_stop(line, [a])
        self.out.write('  EPD DATA QUALITY passed. Next: EPD REPORT '
                       '"file.csv"')

    def _dq_stop(self, line: int, analyses: List[Dict]):
        count = sum(len(a["errors"]) for a in analyses)
        if not count:
            return
        unrated = any(a["unrated"] for a in analyses)
        hint = ("Replace or re-declare the data, rebuild what changed, "
                "then run EPD SYSTEMS, EPD CHECK, EPD CALCULATE and EPD "
                "DATA QUALITY again.")
        if unrated:
            hint = ("Add the missing RATING lines to each BRIDGE or "
                    "process (EDIT PROCESS \"name\" ... RATING GEOGRAPHY "
                    "\"level\" REASON \"why\" ... END EDIT), then run EPD "
                    "DATA QUALITY again. EPD DQ SHEET \"file.csv\" lists "
                    "every dataset that needs them. " + hint)
        raise BasicError(
            f"EPD DATA QUALITY found {count} problem"
            f"{'s' if count != 1 else ''} (listed above). Programme rules "
            f"have no override.", line, hint=hint)

    # ── per scenario ─────────────────────────────────────────

    def _held_by(self, code: str) -> set:
        """The names of the parameters a module's own processes and
        bridges can be varied through."""
        cache = self.modules.setdefault(code, {"subs": []})
        if "held" not in cache:
            walk = self._walk(code)
            used = self.bridge.model_parameters(
                walk["direct"] + walk["upstream"])
            if "error" in used:
                raise BasicError(
                    f"Module {code}: could not read its parameters: "
                    f"{used['error']}")
            cache["held"] = set(used["local"]) | set(used["global"])
            cache["dependent"] = set(used["dependent"])
        return cache["held"]

    def _where_held(self, names: List[str], line: int,
                    command: str) -> Dict[str, List[str]]:
        """{parameter: [modules that hold it]}. A name no module holds
        is an error naming it."""
        where: Dict[str, List[str]] = {n: [] for n in names}
        dependent = set()
        for code in self.d["modules"]:
            held = self._held_by(code)
            dependent |= self.modules[code]["dependent"]
            for n in names:
                if n in held:
                    where[n].append(code)
        lost = [n for n, codes in where.items() if not codes]
        if lost:
            calculated = [n for n in lost if n in dependent]
            if calculated:
                raise BasicError(
                    f"{', '.join(calculated)} "
                    f"{'is' if len(calculated) == 1 else 'are'} calculated "
                    f"from a formula and cannot be set.", line,
                    hint="Vary the parameters the formula uses.")
            raise BasicError(
                f"No module of the EPD holds the parameter"
                f"{'s' if len(lost) != 1 else ''} {', '.join(lost)}.", line,
                hint=f"{command} varies parameters of the EPD's own "
                     f"processes and bridges, and the global parameters "
                     f"their formulas use. Check the spelling: SHOW SYSTEM "
                     f"\"module system\" PARAMS lists what a module holds.")
        return where

    def _dq_scenarios(self, line: int, parameter_set: str, from_file: str):
        """EPD DATA QUALITY PARAMETER SET "name" / FROM "file.csv": the
        same analysis and the same checks, once per scenario."""
        systems = self._require_systems(line, "EPD DATA QUALITY")
        scenarios: Dict[str, Dict[str, float]] = {}
        if from_file:
            data = self.bridge.read_scenarios_csv(from_file)
            if "error" in data:
                raise BasicError(
                    data["error"], line,
                    hint="The file has a column called Parameter and one "
                         "column per scenario; each row gives a "
                         "parameter's value in each scenario.")
            scenarios = data["scenarios"]
        else:
            values: Dict[str, float] = {}
            found = False
            for code, system in systems.items():
                got = self.bridge.get_system_fields(system["id"])
                if "error" in got:
                    raise BasicError(f"Module {code}: {got['error']}", line)
                for ps in got.get("parameter_sets", []):
                    if ps["name"] == parameter_set:
                        found = True
                        for v in ps["values"]:
                            values[v["name"]] = v["value"]
            if not found:
                raise BasicError(
                    f"No module system has a parameter set called "
                    f"'{parameter_set}'.", line,
                    hint="A parameter set is stored on a product system: "
                         "EDIT SYSTEM \"module system\" ... PARAMETER SET "
                         f"\"{parameter_set}\" ... END PARAMETER SET ... "
                         "END EDIT. SHOW SYSTEM \"module system\" SETS "
                         "lists them.")
            scenarios = {parameter_set: values}
        names = sorted({n for vals in scenarios.values() for n in vals})
        self._where_held(names, line, "EPD DATA QUALITY")
        analyses = []
        for label, values in scenarios.items():
            self.out.write(f"  Scenario {label}: "
                           + ", ".join(f"{n} = {v:g}"
                                       for n, v in values.items()))
            a = self._dq_analyse(line, parameters=values, label=label)
            self._dq_print(a)
            analyses.append(a)
        self.i._emit("epd_data_quality_scenarios", {
            "epd": self.name,
            "scenarios": {a["label"]: self._public(a) for a in analyses}})
        self._dq_stop(line, analyses)
        self.out.write(
            f"  EPD DATA QUALITY passed for {len(analyses)} scenario"
            f"{'s' if len(analyses) != 1 else ''}. The declared results "
            f"are the model as it stands: run EPD DATA QUALITY on its own "
            f"for those.")

    # ── the register and the assessment table ────────────────

    def _register(self, a: Dict) -> List[Dict]:
        """One row per dataset the assessment has to cover or that is
        above the GWP-GHG threshold, with what stands behind it."""
        rows = []
        entries, needed = a["_entries"], a["_needed"]
        for e in sorted(entries.values(), key=lambda e: e["name"]):
            if e["id"] not in needed and not e.get("gwp_row"):
                continue
            behind = {}
            if e["is_bridge"]:
                own = self.bridge.dataset_metadata(e["id"])
                if "error" not in own and own["provider_id"]:
                    behind = self.bridge.dataset_metadata(own["provider_id"])
                    if "error" in behind:
                        behind = {}
            ratings = e["ratings"]
            rows.append({
                "dataset": e["name"],
                "kind": "bridge" if e["is_bridge"] else "process",
                "modules": ", ".join(e["modules"]),
                "above_threshold": bool(e.get("gwp_row")),
                "gwp_share": e.get("gwp_share", 0.0),
                "needed_for": needed.get(e["id"], 0),
                "data_category": e["effective"].lower(),
                "source_type": e["tags"].get("source", ""),
                "source": e["tags"].get("provider", ""),
                "year": e["year"] or "",
                "background": behind.get("name", ""),
                "background_location": behind.get("location", ""),
                "valid_from": behind.get("valid_from", ""),
                "valid_until": behind.get("valid_until", ""),
                "technology": behind.get("technology", ""),
                "geography": behind.get("geography", ""),
                "time": behind.get("time", ""),
                "dq_system": behind.get("dq_system", ""),
                "ratings": ratings,
            })
        return rows

    def _remember_register(self, a: Dict) -> List[Dict]:
        rows = self._register(a)
        self.i.runtime.dq_register[self.name] = rows
        return rows

    def dq_sheet(self, line: int, filename: str):
        """EPD DQ SHEET "file.csv": the register of the datasets the
        assessment has to cover, with the ratings recorded so far."""
        self._dq_require(line, "EPD DQ SHEET")
        a = self._dq_analyse(line)
        rows = self._remember_register(a)
        p = self.profile
        head = ["Dataset", "Kind", "Modules",
                f"Above {p.gwp_row_threshold_pct:g}% of GWP-GHG in A1-A3",
                "Share of GWP-GHG in A1-A3 (%)",
                f"Impact indicators it is needed for "
                f"(of {a['impact_indicators']})",
                "Data category", "Source type", "Source", "Reference year",
                "Background process", "Background location", "Valid from",
                "Valid until", "Technology description",
                "Geography description", "Time description", "DQ system"]
        for aspect in en15804.DQ_ASPECTS:
            head += [f"Rating: {aspect.lower()}", f"Reason: {aspect.lower()}"]
        table = [head]
        for r in rows:
            line_ = [r["dataset"], r["kind"], r["modules"],
                     "yes" if r["above_threshold"] else "no",
                     f"{r['gwp_share']:.2f}", r["needed_for"],
                     r["data_category"], r["source_type"], r["source"],
                     r["year"], r["background"], r["background_location"],
                     r["valid_from"], r["valid_until"], r["technology"],
                     r["geography"], r["time"], r["dq_system"]]
            for aspect in en15804.DQ_ASPECTS:
                rating = r["ratings"].get(aspect, {})
                line_ += [rating.get("level", ""), rating.get("reason", "")]
            table.append(line_)
        try:
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(table)
        except OSError as e:
            raise BasicError(f"Could not write '{filename}': {e}", line)
        unrated = [r["dataset"] for r in rows if r["needed_for"] and any(
            aspect not in r["ratings"] for aspect in en15804.DQ_ASPECTS)]
        self.out.write(f"  Data quality register saved to {filename}: "
                       f"{len(rows)} datasets.")
        if unrated:
            self.out.write(
                f"  {len(unrated)} of them still "
                f"{'need' if len(unrated) != 1 else 'needs'} ratings: "
                + ", ".join(unrated) + ".")
            self.out.write(
                f"  The scale ({p.dq_scheme}; {en15804.CLAUSE_DQ_SCHEME}): "
                + ", ".join(p.dq_levels) + ".")
        else:
            self.out.write("  Every dataset the assessment has to cover is "
                           "rated.")
        self.i._emit("epd_dq_sheet", {
            "file": filename, "epd": self.name, "datasets": rows,
            "unrated": unrated})

    def dq_table(self, line: int, filename: str):
        """EPD DQ TABLE "file.md": the assessment table for the
        accompanying report, over every product assessed in this
        session."""
        self._dq_require(line, "EPD DQ TABLE")
        a = self._dq_analyse(line)
        self._remember_register(a)
        p = self.profile
        register = self.i.runtime.dq_register
        products = list(register)
        letters = {name: chr(ord("A") + i) if i < 26 else str(i + 1)
                   for i, name in enumerate(products)}
        merged: Dict[str, Dict] = {}
        for product, rows in register.items():
            for r in rows:
                if not r["needed_for"]:
                    continue
                m = merged.setdefault(r["dataset"], {
                    "dataset": r["dataset"], "background": r["background"],
                    "products": [], "ratings": r["ratings"]})
                m["products"].append(product)
                if r["ratings"]:
                    m["ratings"] = r["ratings"]

        def cell(text: str) -> str:
            return str(text).replace("|", "/").replace("\n", " ")

        lines = ["# Data quality assessment", ""]
        lines.append(
            f"This assessment covers the data that together give at least "
            f"{p.coverage_pct:g}% of the result of each declared "
            f"environmental impact indicator ({p.clause('data_quality')}; "
            f"{en15804.CLAUSE_DQ_SCHEME}). Geographical, technical and "
            f"temporal representativeness are rated on the scale of "
            f"{p.dq_scheme}: {', '.join(p.dq_levels)}.")
        lines.append("")
        if len(products) > 1:
            lines.append("## Products")
            lines.append("")
            for name in products:
                lines.append(f"- {letters[name]} = {name}")
            lines.append("")
        lines.append("## Summary table")
        lines.append("")
        lines.append("| Dataset | Products | "
                     + " | ".join(en15804.DQ_ASPECT_TITLES[a_]
                                  for a_ in en15804.DQ_ASPECTS) + " |")
        lines.append("|---|---|---|---|---|")
        unrated = []
        for m in sorted(merged.values(), key=lambda m: m["dataset"]):
            name = m["dataset"]
            if m["background"]:
                name += f" (background: {m['background']})"
            shown = (", ".join(letters[x] for x in m["products"])
                     if len(products) > 1 else m["products"][0])
            cells = []
            for aspect in en15804.DQ_ASPECTS:
                rating = m["ratings"].get(aspect)
                if rating is None:
                    cells.append("Not rated")
                    if m["dataset"] not in unrated:
                        unrated.append(m["dataset"])
                else:
                    cells.append(f"{rating['level']}. {rating['reason']}")
            lines.append("| " + " | ".join(
                cell(c) for c in [name, shown] + cells) + " |")
        lines.append("")
        try:
            with open(filename, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except OSError as e:
            raise BasicError(f"Could not write '{filename}': {e}", line)
        self.out.write(
            f"  Data quality assessment table saved to {filename}: "
            f"{len(merged)} datasets, {len(products)} product"
            f"{'s' if len(products) != 1 else ''}.")
        if unrated:
            self.out.write("  Not rated yet: " + ", ".join(unrated) + ".")
        self.i._emit("epd_dq_table", {
            "file": filename, "products": products,
            "datasets": sorted(merged), "unrated": unrated})

    # ── biogenic carbon ──────────────────────────────────────

    def _biogenic_tolerances(self):
        p = self.profile
        if p is not None:
            return (p.biogenic_balance_tolerance_pct,
                    p.biogenic_content_tolerance_pct)
        return (en15804.BIOGENIC_BALANCE_TOLERANCE_PCT,
                en15804.BIOGENIC_CONTENT_TOLERANCE_PCT)

    def _biogenic_clause(self, standard: str) -> str:
        if self.profile is not None:
            return f"{standard}; {self.profile.pcr_clauses['biogenic']}"
        return standard

    def biogenic_check(self, line: int, split: Dict[str, Dict]) -> Dict:
        """
        The carbon balances of a product that contains biogenic carbon.
        split: {module: {"matching": biogenic CO2 in GWP-biogenic,
        "other": the rest of GWP-biogenic}}. Returns what was found;
        raises BasicError when a balance does not close.
        """
        d = self.d
        content = d["biogenic_content"]
        per_c = en15804.CO2_PER_KG_CARBON
        product = content["product"] * per_c
        packaging = content["packaging"] * per_c
        stored = product + packaging
        balance_pct, content_pct = self._biogenic_tolerances()
        floor = en15804.BIOGENIC_FLOOR_KG_CO2
        co2 = {code: split[code]["matching"] for code in d["modules"]}
        a_to_c = [c for c in d["modules"] if c != "D"]
        stage = [c for c in ("A1", "A2", "A3") if c in co2]
        uptake = sum(co2[c] for c in stage)
        total = sum(co2[c] for c in a_to_c)
        # Packaging carbon is released in A5. Where A5 is not declared
        # its release is reported in A1 to A3, so only the product's
        # carbon is left there.
        expected = -(product + (packaging if "A5" in d["modules"] else 0.0))
        exports = d.get("biogenic_exports") or []
        export_co2 = sum(x["carbon"] for x in exports) * per_c
        per_module = ", ".join(f"{c} {_fmt(co2[c])}" for c in a_to_c)
        found = {
            "content_product_kg_c": content["product"],
            "content_packaging_kg_c": content["packaging"],
            "stored_kg_co2": stored, "biogenic_co2": co2,
            "uptake_a1_a3": uptake, "expected_a1_a3": expected,
            "sum_a_to_c": total, "exports": exports,
            "other_gases": {c: split[c]["other"] for c in d["modules"]}}
        problems = []

        gap = uptake - expected
        if abs(gap) > max(floor, content_pct / 100.0 * abs(expected)):
            text = (
                f"Biogenic CO2 in A1 to A3 is {_fmt(uptake)} kg CO2 eq., "
                f"but the declared content ({content['product']:g} kg C in "
                f"the product"
                + (f", {content['packaging']:g} kg C in the packaging"
                   if content["packaging"] else "")
                + f") is {_fmt(expected)} kg CO2 eq. "
                  f"({self._biogenic_clause(en15804.CLAUSE_BIOGENIC_UPTAKE)}"
                  f").")
            if expected and uptake < expected:
                text += (f" The model takes up {uptake / expected:.2f} "
                         f"times the carbon that is in the product.")
            if export_co2 and abs(gap + export_co2) <= max(
                    floor, content_pct / 100.0 * abs(expected)):
                names = ", ".join(f"{x['item']} ({x['carbon']:g} kg C)"
                                  for x in exports)
                text += (
                    f" The difference is the carbon of the declared "
                    f"co-products: {names}. They leave A1 to A3 without "
                    f"their carbon. A co-product carries its carbon out "
                    f"with a factor of +1 whatever allocation the process "
                    f"uses ({en15804.CLAUSE_BIOGENIC_COPRODUCTS}).")
            elif uptake < expected:
                text += (
                    " Uptake counts only the carbon that ends up in the "
                    "product: carbon in co-products leaves with +1 (declare "
                    "them with BIOGENIC EXPORT), and uptake that comes with "
                    "background data for the whole tree is not the "
                    "product's.")
            problems.append(text)

        if abs(total) > max(floor, balance_pct / 100.0 * stored):
            released = sum(co2[c] for c in a_to_c if c not in stage)
            text = (
                f"Biogenic CO2 does not balance over A to C: the sum is "
                f"{_fmt(total)} kg CO2 eq., not zero ({per_module}) "
                f"({self._biogenic_clause(en15804.CLAUSE_BIOGENIC_FACTORS)}"
                f").")
            if uptake < 0 and released < -uptake:
                text += (
                    f" The modules after A3 release {_fmt(released)} of the "
                    f"{_fmt(-uptake)} taken up. Carbon that leaves for "
                    f"reuse or recycling counts as an emission in the "
                    f"module where it leaves "
                    f"({en15804.CLAUSE_BIOGENIC_END_OF_LIFE}).")
            problems.append(text)

        if "D" in co2 and abs(co2["D"]) > max(
                floor, balance_pct / 100.0 * stored):
            problems.append(
                f"Biogenic CO2 in module D is {_fmt(co2['D'])} kg CO2 eq., "
                f"not zero. In module D the uptake of an avoided product "
                f"is offset by an equal emission "
                f"({self._biogenic_clause(en15804.CLAUSE_BIOGENIC_UPTAKE)}"
                f").")
        found["problems"] = problems
        found["passed"] = not problems
        return found

    # ── EPD SENSITIVITY ──────────────────────────────────────

    def sensitivity(self, line: int, percent: float, groups: List[Dict],
                    save: str = ""):
        if not self.results:
            raise BasicError(
                "EPD SENSITIVITY needs the baseline results.", line,
                hint="Run EPD CALCULATE first.")
        systems = self._require_systems(line, "EPD SENSITIVITY")
        d = self.d
        names = [g["name"] for g in groups]
        if len(set(names)) != len(names):
            dupe = next(n for n in names if names.count(n) > 1)
            raise BasicError(f"The group '{dupe}' is given twice.", line)
        where = {}
        for g in groups:
            self.i._at(g["line"])
            where[g["name"]] = self._where_held(g["params"], g["line"],
                                                "EPD SENSITIVITY")
        self.i._at(line)
        a_to_c = [c for c in d["modules"] if c != "D"]
        cats = [c["name"] for c in self.categories]
        factor = percent / 100.0
        runs: Dict[str, Dict[str, Dict[str, float]]] = {}
        calculated = 0
        for g in groups:
            held = where[g["name"]]
            touched = [c for c in d["modules"]
                       if any(c in codes for codes in held.values())]
            self.out.write(
                f"  {g['name']}: {', '.join(g['params'])} in "
                f"{', '.join(touched)}...")
            for sign, mult in (("-", 1.0 - factor), ("+", 1.0 + factor)):
                per_module = {c: self.results[c] for c in d["modules"]}
                for code in touched:
                    mine = [n for n, codes in held.items() if code in codes]
                    got = self.bridge.calculate_scaled(
                        systems[code]["id"], d["method"], mine, mult)
                    if "error" in got:
                        raise BasicError(
                            f"Module {code}, group '{g['name']}': "
                            f"{got['error']}", g["line"])
                    per_module[code] = got["impacts"]
                    calculated += 1
                runs[f"{g['name']} {sign}{percent:g}%"] = per_module

        def scope_sum(per_module, cat, codes):
            return sum(per_module[c].get(cat, 0.0) for c in codes)

        scopes = [("A to C", a_to_c)]
        if "D" in d["modules"]:
            scopes.append(("D", ["D"]))
        table = {}
        for scope, codes in scopes:
            rows = []
            for cat in cats:
                row = {"indicator": cat, "unit": self.units.get(cat, ""),
                       "baseline": scope_sum(self.results, cat, codes)}
                for label, per_module in runs.items():
                    row[label] = scope_sum(per_module, cat, codes)
                rows.append(row)
            table[scope] = rows
        labels = list(runs)

        out = self.out
        gwp = self.gwp_indicator or cats[0]
        out.write(f"  EPD SENSITIVITY: {self.name}, each group down and up "
                  f"by {percent:g}% ({calculated} calculations; modules "
                  f"that hold none of a group's parameters keep their "
                  f"baseline).")
        for scope, _ in scopes:
            row = next(r for r in table[scope] if r["indicator"] == gwp)
            out.write(f"  '{gwp}', modules {scope}: baseline "
                      f"{_fmt(row['baseline'])} {row['unit']}")
            for g in groups:
                lo = row[f"{g['name']} -{percent:g}%"]
                hi = row[f"{g['name']} +{percent:g}%"]
                base = row["baseline"]

                def change(v):
                    return (f"{100.0 * (v - base) / abs(base):+.2f}%"
                            if base else "n/a")
                out.write(f"    {g['name']:<32} {_fmt(lo):>14} "
                          f"({change(lo)})  {_fmt(hi):>14} ({change(hi)})")
        out.write("  Module D is shown on its own: it is never added to "
                  "A to C.")
        if save:
            head = ["Indicator", "Unit", "Modules", "Baseline"] + labels
            rows = [head]
            for scope, _ in scopes:
                for r in table[scope]:
                    rows.append([r["indicator"], r["unit"], scope,
                                 r["baseline"]] + [r[lb] for lb in labels])
            try:
                with open(save, "w", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerows(rows)
            except OSError as e:
                raise BasicError(f"Could not write '{save}': {e}", line)
            out.write(f"  Sensitivity table saved to {save} "
                      f"({len(cats)} indicators).")
        self.i._emit("epd_sensitivity", {
            "epd": self.name, "percent": percent,
            "groups": [{"name": g["name"], "parameters": g["params"],
                        "modules": sorted({c for codes in
                                           where[g["name"]].values()
                                           for c in codes},
                                          key=d["modules"].index)}
                       for g in groups],
            "calculations": calculated, "table": table,
            "file": save or None})

    # ── EPD EXPORT MODEL ─────────────────────────────────────

    def export_model(self, line: int, filename: str):
        if not filename.lower().endswith(".json"):
            raise BasicError(
                f"'{filename}' is not a .json file name.", line,
                hint='For example: EPD EXPORT MODEL "model.json"')
        systems = [s["id"] for s in (
            self._system_of(c) for c in self.d["modules"]) if s]
        data = self.bridge.export_model(self.folder, systems, self.name)
        if "error" in data:
            raise BasicError(data["error"], line)
        d = self.d
        data["metadata"]["epd"] = {
            "name": d["name"], "type": d["type"],
            "unit": f"{d['unit_amount']:g} {d['unit']}",
            "method": d["method"], "modules": d["modules"],
            "programme": d["programme"], "pcr": d["pcr"],
            "database": d["database"]}
        try:
            with open(filename, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except OSError as e:
            raise BasicError(f"Could not write '{filename}': {e}", line)
        m = data["metadata"]
        self.out.write(
            f"  Model saved to {os.path.abspath(filename)}: "
            f"{m['process_count']} processes, {m['total_exchanges']} "
            f"exchanges, {m['flow_count']} flows, "
            f"{m['global_parameter_count']} global parameters, "
            f"{m['system_count']} product systems.")
        self.i._emit("epd_export_model", {"file": filename, **m})
