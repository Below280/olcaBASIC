"""Finding the live baseline that belongs to the open database."""

import json
import os
import re
from pathlib import Path

import pytest


def _find_baselines():
    env = os.getenv("OLCA_LIVE_BASELINE")
    if env:
        return [Path(env)]
    found = []
    for parent in Path(__file__).resolve().parents:
        first = parent / "REBUILD_PLAN" / "live_baseline.json"
        if first.exists():
            found.append(first)
        second = parent / "REBUILD_PLAN_2"
        if second.is_dir():
            found.extend(sorted(second.glob("live_baseline_*.json")))
        if found:
            break
    return found


def _mismatch(info, expected):
    """Why a baseline does not belong to the open database, or ""."""
    # A few extra entities are fine (these tests leave a flow behind,
    # and the reference model may or may not be present).
    for kind in ("processes", "flows"):
        if abs(info.get(kind, 0) - expected[kind]) > 25:
            return (f"{info.get(kind)} {kind} against {expected[kind]}")
    if info.get("impact_methods") != expected["impact_methods"]:
        return (f"{info.get('impact_methods')} impact methods against "
                f"{expected['impact_methods']}")
    return ""


def matching_baseline(engine):
    """The baseline captured from the database that is open. Skips the
    test (with the reason) when there is none."""
    paths = [p for p in _find_baselines() if p.exists()]
    if not paths:
        pytest.skip("no live baseline: set OLCA_LIVE_BASELINE to the path of "
                    "a live_baseline file")
    info = engine.get_database_info()
    reasons = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        why = _mismatch(info, data["database_info"])
        if not why:
            return data
        reasons.append(f"{path.name}: {why}")
    # A different database gives different numbers, so say so instead
    # of failing.
    pytest.skip("no baseline was captured from the open database ("
                + "; ".join(reasons) + ")")


# ── the baseline program and the bridge rule ─────────────────
#
# The baselines were captured with programs that name background
# processes straight in MAKE PROCESS. From 0.4.0 every background input
# goes through a bridge and there is no way round that, so the program
# is rewritten here: each such input gets a bridge of its own, and the
# process uses the bridge. A bridge passes its provider through one for
# one, so every result must still match the baseline to its tolerance.
# The comparisons of structure look through the bridges (see_through).

BRIDGE_SHORT = "olcaBASIC live test input"
_OPTION = re.compile(r'\s(LOCATION|PROVIDER)\s+"([^"]+)"')
_INPUT = re.compile(r'^(\s*)INPUT USE PROCESS "([^"]+)",\s*(.*)$')
_KEYWORD = re.compile(r'\s(LOCATION|PROVIDER|UNCERTAINTY|PEDIGREE|COMMENT|'
                      r'COST|SITE|BASE|FORMULA)\b')


def bridged(program):
    """(program with every background input behind a bridge, the names
    of the bridges). Bridges are written just before the first MAKE
    PROCESS line, so they land in the program's own process folder."""
    lines, bridges, names = [], [], []
    for line in program.splitlines():
        m = _INPUT.match(line)
        if not m or m.group(2).startswith("BRIDGE |"):
            lines.append(line)
            continue
        indent, provider, rest = m.groups()
        cut = _KEYWORD.search(" " + rest)
        head = rest if not cut else rest[:cut.start() - 1 if cut.start() else 0]
        unit = head.rsplit(",", 1)[1].strip()
        options = dict(_OPTION.findall(" " + rest))
        tail = _OPTION.sub("", " " + rest).strip()
        short = f"{BRIDGE_SHORT} {len(names) + 1}"
        name = f"BRIDGE | {short} | {unit}"
        names.append(name)
        target = options.get("PROVIDER", provider)
        where = (f' LOCATION "{options["LOCATION"]}"'
                 if "LOCATION" in options and "PROVIDER" not in options else "")
        bridges += [f'BRIDGE "{short}", {unit}',
                    f'  PROVIDER "{target}"{where}', "END BRIDGE"]
        lines.append(f'{indent}INPUT USE PROCESS "{name}", {tail}')
    at = next((i for i, l in enumerate(lines)
               if l.lstrip().startswith("MAKE PROCESS")), len(lines))
    return "\n".join(lines[:at] + bridges + lines[at:]), names


def see_through(engine, details):
    """Process details with each input from a bridge replaced by what
    the bridge passes on: the flow and the provider behind it."""
    out = dict(details)
    rows = []
    for ex in details["exchanges"]:
        ex = dict(ex)
        provider = ex.get("provider") or ""
        if ex.get("is_input") and provider.startswith("BRIDGE |"):
            found = engine.search_processes(provider)["processes"]
            found = [p for p in found if p["name"] == provider]
            assert len(found) == 1, provider
            inner = [e for e in engine.get_process_details(
                found[0]["id"])["exchanges"] if e["is_input"]]
            assert len(inner) == 1, provider
            assert inner[0]["amount"] == 1.0 and not inner[0]["formula"]
            ex["flow"] = inner[0]["flow"]
            ex["provider"] = inner[0]["provider"]
        rows.append(ex)
    out["exchanges"] = rows
    return out
