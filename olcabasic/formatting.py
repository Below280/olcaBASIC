"""
Output formatting for olcaBASIC.

Handles result tables, search results, and general terminal output.
Uses only built-in Python — no external dependencies.
"""

from typing import Dict, List, Any, Optional
import csv
import io


def format_table(headers: List[str], rows: List[List[str]],
                 max_widths: Optional[List[int]] = None) -> str:
    """Format a list of rows as an aligned text table."""
    if not rows:
        return "  (no results)"

    # Calculate column widths
    col_count = len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row[:col_count]):
            widths[i] = max(widths[i], len(str(cell)))

    # Apply max widths if specified
    if max_widths:
        for i, mw in enumerate(max_widths):
            if mw and i < len(widths):
                widths[i] = min(widths[i], mw)

    # Build format string
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)

    lines = []
    lines.append("  " + fmt.format(*headers))
    lines.append("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        # Mark cut-off cells with '...' so a truncated name is never
        # mistaken for the real one (and copied into a DIR path)
        cells = []
        for i, c in enumerate(row[:col_count]):
            c = str(c)
            if i < len(widths) and len(c) > widths[i]:
                c = c[:max(widths[i] - 3, 0)] + "..."
            cells.append(c)
        # Pad if row is shorter than headers
        while len(cells) < col_count:
            cells.append("")
        lines.append("  " + fmt.format(*cells))

    return "\n".join(lines)


def format_impacts(results: Dict) -> str:
    """Format impact calculation results."""
    impacts = results.get("impacts", [])
    if not impacts:
        return "  No impact results."

    headers = ["Impact Category", "Amount", "Unit"]
    rows = []
    for imp in impacts:
        amt = imp.get("amount", 0)
        amt_str = f"{amt:.4e}" if abs(amt) > 1e6 or (
            abs(amt) < 0.01 and amt != 0) else f"{amt:.6f}"
        rows.append([
            imp.get("category", "?"),
            amt_str,
            imp.get("unit", ""),
        ])

    lines = [
        f"  System: {results.get('system', '?')}",
        f"  Method: {results.get('method', '?')}",
        "",
        format_table(headers, rows, max_widths=[50, 15, 20]),
    ]
    return "\n".join(lines)


def format_scenarios(results: Dict) -> str:
    """Format scenario comparison results."""
    scenario_results = results.get("results", {})
    if not scenario_results:
        return "  No scenario results."

    scenario_names = list(scenario_results.keys())
    first = scenario_results[scenario_names[0]]

    headers = ["Impact Category"] + scenario_names
    rows = []
    for imp in first:
        cat_name = imp.get("category", "?")
        cat_id = imp.get("category_id", "")
        row = [cat_name]
        for sname in scenario_names:
            s_impacts = scenario_results[sname]
            val = None
            for si in s_impacts:
                if si.get("category_id") == cat_id:
                    val = si.get("amount", 0)
                    break
            if val is not None:
                row.append(f"{val:.4e}" if abs(val) > 1e6 else f"{val:.6f}")
            else:
                row.append("N/A")
        rows.append(row)

    lines = [
        f"  System: {results.get('system', '?')}",
        f"  Method: {results.get('method', '?')}",
        f"  Scenarios: {len(scenario_names)}",
        "",
        format_table(headers, rows, max_widths=[40] + [18] * len(scenario_names)),
    ]

    if results.get("warning"):
        lines.append(f"\n  WARNING: {results['warning']}")

    return "\n".join(lines)


def format_sensitivity(results: Dict) -> str:
    """Format sensitivity analysis results."""
    baseline = results.get("baseline", {})
    sensitivity = results.get("sensitivity", {})
    variation = results.get("variation_pct", 20)

    if not baseline or not sensitivity:
        return "  No sensitivity results."

    param_names = results.get("tested", [])
    headers = ["Impact Category", "Baseline"]
    for p in param_names:
        headers.append(f"{p} -{variation}%")
        headers.append(f"{p} +{variation}%")

    rows = []
    for cat_name, cat_data in baseline.items():
        base_amt = cat_data.get("amount", 0)
        row = [cat_name, f"{base_amt:.4e}"]
        for p in param_names:
            p_data = sensitivity.get(p, {})
            minus_val = p_data.get("minus", {}).get(cat_name, 0)
            plus_val = p_data.get("plus", {}).get(cat_name, 0)

            # Calculate percentage change
            if abs(base_amt) > 1e-30:
                minus_pct = ((minus_val - base_amt) / base_amt) * 100
                plus_pct = ((plus_val - base_amt) / base_amt) * 100
                row.append(f"{minus_val:.4e} ({_pct(minus_pct)})")
                row.append(f"{plus_val:.4e} ({_pct(plus_pct)})")
            else:
                row.append(f"{minus_val:.4e}")
                row.append(f"{plus_val:.4e}")
        rows.append(row)

    lines = [
        f"  System: {results.get('system', '?')}",
        f"  Method: {results.get('method', '?')}",
        f"  Variation: +/-{variation}%",
        f"  Parameters tested: {', '.join(param_names)}",
        "",
        format_table(headers, rows),
    ]

    if results.get("missing"):
        lines.append(
            f"\n  Missing parameters: {', '.join(results['missing'])}")

    return "\n".join(lines)


def _pct(p: float) -> str:
    """Percent change with enough decimals that small effects don't
    show as a misleading 0.0%."""
    if p == 0:
        return "0%"
    if abs(p) >= 1:
        return f"{p:+.1f}%"
    if abs(p) >= 0.01:
        return f"{p:+.2f}%"
    return f"{p:+.1e}%"


def format_flows(results: Dict) -> str:
    """Format flow search results, with category so elementary flow
    compartments are visible."""
    flows = results.get("flows", [])
    rows = []
    for f in flows:
        ftype = str(f.get("flow_type", "")).replace("FlowType.", "")
        ftype = ftype.replace("_FLOW", "").lower()
        rows.append([f.get("name", "?"), ftype, f.get("ref_unit", "") or "",
                     f.get("category", "")])
    lines = [f"  {len(flows)} results"
             + (" (limit reached, narrow the search)" if len(flows) >= 20
                else "")]
    if rows:
        lines.append(format_table(["Name", "Type", "Unit", "Category"],
                                  rows, max_widths=[50, 11, 8, 70]))
    return "\n".join(lines)


def format_processes(results: Dict) -> str:
    """Format process search results."""
    procs = results.get("processes", [])
    # UUID column: it's what PROVIDER, LINK and MOVE take when
    # several processes share a name. Location column (when the
    # search returned it): what LOCATION takes.
    with_location = any("location" in p for p in procs)
    if with_location:
        headers = ["Name", "Location", "Category", "UUID"]
        rows = [[p.get("name", "?"), p.get("location", ""),
                 p.get("category", ""), p.get("id", "")] for p in procs]
        widths = [70, 14, 50, 36]
    else:
        headers = ["Name", "Category", "UUID"]
        rows = [[p.get("name", "?"), p.get("category", ""), p.get("id", "")]
                for p in procs]
        widths = [70, 70, 36]

    count = results.get("count", len(procs))
    total = results.get("total_matches", count)
    lines = [f"  {count} results (of {total} total)"]
    if rows:
        lines.append(format_table(headers, rows, max_widths=widths))
    if results.get("truncated"):
        lines.append(f"  Showing the first {count}. Narrow the search with "
                     f"more of the name, AT \"location\" or IN \"folder\".")
    return "\n".join(lines)


def format_methods(results: Dict) -> str:
    """Format method listing."""
    methods = results.get("methods", [])
    headers = ["Name"]
    rows = [[m.get("name", "?")] for m in methods]
    lines = [f"  {len(methods)} methods"]
    if rows:
        lines.append(format_table(headers, rows))
    return "\n".join(lines)


def format_systems(results: Dict) -> str:
    """Format system listing."""
    systems = results.get("systems", [])
    headers = ["Name"]
    rows = [[s.get("name", "?")] for s in systems]
    lines = [f"  {len(systems)} product systems"]
    if rows:
        lines.append(format_table(headers, rows))
    return "\n".join(lines)


def exchange_amount(ex: Dict, param_values: Dict) -> str:
    """The amount to show for an exchange. The engine stores plain-number
    amounts as process parameters (p01_...), so show the value rather
    than the parameter's name; real formulas are shown as written."""
    formula = ex.get("formula")
    if formula:
        name = formula.strip()
        if name in param_values and param_values[name] is not None:
            v = param_values[name]
            return f"{v:.6g}" if isinstance(v, float) else str(v)
        return formula
    amt = ex.get("amount", 0)
    return f"{amt:.4e}" if abs(amt) > 1e4 else f"{amt:.6g}"


def param_values_of(results: Dict) -> Dict:
    return {p.get("name"): p.get("value")
            for p in results.get("parameters", []) or []
            if not p.get("formula")}


def format_dq_systems(results: Dict) -> str:
    """Data quality systems with their indicators numbered in position
    order, which is the order of the scores in PEDIGREE (...)."""
    systems = results.get("dq_systems", [])
    if not systems:
        return "  " + results.get("note", "No data quality systems in this database.")
    lines = [f"  {len(systems)} data quality systems"]
    for dq in systems:
        lines.append("")
        lines.append(f"  {dq.get('name', '?')}")
        for k, ind in enumerate(dq.get("indicators", []), 1):
            pos = ind.get("position") or k
            lines.append(f"    {pos}. {ind.get('name', '?')}")
    lines.append("")
    lines.append("  PEDIGREE (...) takes one score per indicator, in this order.")
    return "\n".join(lines)


def format_flow_details(flow: Dict, units_only: bool = False) -> str:
    """A flow's properties, with factors relative to the reference."""
    props = flow.get("properties", [])
    lines = []
    if not units_only:
        lines += [f"  Name:      {flow.get('name', '?')}",
                  f"  Type:      {flow.get('type', '')}",
                  f"  Category:  {flow.get('category', '')}", ""]
    ref = next((p for p in props if p.get("reference")), None)
    lines.append(f"  {flow.get('name', '?')}: {len(props)} flow "
                 f"propert{'y' if len(props) == 1 else 'ies'}")
    rows = []
    for p in props:
        f = p.get("factor")
        rows.append([p.get("name", "?"), f"{f:.6g}" if f is not None else "?",
                     p.get("unit", ""), "reference" if p.get("reference") else ""])
    lines.append(format_table(["Property", "Factor", "Unit", ""], rows))
    if ref:
        for p in props:
            if p is not ref and p.get("factor"):
                lines.append(f"  1 {ref.get('unit', '')} = {p['factor']:.6g} "
                             f"{p.get('unit', '')}")
    return "\n".join(lines)


def format_process_details(results: Dict) -> str:
    """Format detailed process info."""
    if "error" in results:
        return f"  Error: {results['error']}"

    lines = [
        f"  Name:        {results.get('name', '?')}",
        f"  Category:    {results.get('category', '')}",
        f"  Location:    {results.get('location', '')}",
    ]
    if results.get("description"):
        lines.append(f"  Description: {results['description'][:80]}")

    exchanges = results.get("exchanges", [])
    if exchanges:
        lines.append(f"\n  Exchanges ({len(exchanges)}):")
        headers = ["Direction", "Flow", "Amount", "Unit", "QRef", "Provider"]
        rows = []
        values = param_values_of(results)
        for ex in exchanges:
            direction = "INPUT" if ex.get("is_input") else "OUTPUT"
            qref = "*" if ex.get("is_qref") else ""
            amt_str = exchange_amount(ex, values)
            rows.append([
                direction,
                ex.get("flow", "?"),
                amt_str,
                ex.get("unit", ""),
                qref,
                ex.get("provider", "") or "",
            ])
        lines.append(format_table(headers, rows, max_widths=[9, 45, 30, 8, 4, 30]))

    params = results.get("parameters", [])
    if params:
        lines.append(f"\n  Parameters ({len(params)}):")
        headers = ["Name", "Value", "Formula"]
        rows = []
        for p in params:
            rows.append([
                p.get("name", "?"),
                str(p.get("value", "")),
                p.get("formula", "") or "",
            ])
        lines.append(format_table(headers, rows))

    return "\n".join(lines)


def format_database_info(results: Dict) -> str:
    """Format database overview."""
    lines = [
        f"  Status:          {results.get('status', '?')}",
        f"  Processes:       {results.get('processes', '?')}",
        f"  Flows:           {results.get('flows', '?')}",
        f"  Product systems: {results.get('product_systems', '?')}",
        f"  Impact methods:  {results.get('impact_methods', '?')}",
        f"  Parameters:      {results.get('parameters', '?')}",
        f"  Family:          {results.get('database_family', '?')}",
    ]
    return "\n".join(lines)


def format_params(results: Dict) -> str:
    """Format parameter listing."""
    params = results.get("parameters", [])
    if not params:
        return "  No parameters found."

    headers = ["Name", "Value", "Formula"]
    rows = []
    for p in params:
        rows.append([
            p.get("name", "?"),
            str(p.get("value", "")),
            p.get("formula", "") or "",
        ])

    lines = [f"  {len(params)} parameters"]
    lines.append(format_table(headers, rows))
    return "\n".join(lines)


def format_generic(results: Dict) -> str:
    """Format any result dict as readable output."""
    if "error" in results:
        return f"  Error: {results['error']}"

    lines = []
    for key, val in results.items():
        if isinstance(val, list) and len(val) > 5:
            lines.append(f"  {key}: [{len(val)} items]")
        elif isinstance(val, dict):
            lines.append(f"  {key}:")
            for k2, v2 in val.items():
                lines.append(f"    {k2}: {v2}")
        else:
            lines.append(f"  {key}: {val}")
    return "\n".join(lines)


def results_to_csv(results: Dict, results_type: str) -> str:
    """Convert results to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)

    if results_type == "query":
        return query_to_csv(results)

    if results_type == "calculate":
        writer.writerow(["Impact Category", "Amount", "Unit"])
        for imp in results.get("impacts", []):
            writer.writerow([
                imp.get("category", ""),
                imp.get("amount", 0),
                imp.get("unit", ""),
            ])

    elif results_type == "scenarios":
        scenario_names = list(results.get("results", {}).keys())
        writer.writerow(["Impact Category"] + scenario_names)
        if scenario_names:
            first = results["results"][scenario_names[0]]
            for imp in first:
                cat_id = imp.get("category_id", "")
                row = [imp.get("category", "")]
                for sname in scenario_names:
                    for si in results["results"][sname]:
                        if si.get("category_id") == cat_id:
                            row.append(si.get("amount", 0))
                            break
                writer.writerow(row)

    elif results_type == "sensitivity":
        baseline = results.get("baseline", {})
        sensitivity = results.get("sensitivity", {})
        param_names = results.get("tested", [])
        variation = results.get("variation_pct", 20)

        headers = ["Impact Category", "Unit", "Baseline"]
        for p in param_names:
            headers.append(f"{p} -{variation}%")
            headers.append(f"{p} +{variation}%")
        writer.writerow(headers)

        for cat_name, cat_data in baseline.items():
            row = [cat_name, cat_data.get("unit", ""),
                   cat_data.get("amount", 0)]
            for p in param_names:
                p_data = sensitivity.get(p, {})
                row.append(p_data.get("minus", {}).get(cat_name, "N/A"))
                row.append(p_data.get("plus", {}).get(cat_name, "N/A"))
            writer.writerow(row)

    return output.getvalue()


def _scores(entry):
    """'(1;2;4;1;3)' -> [1, 2, 4, 1, 3]; None for missing or 'n.a.'."""
    if not entry:
        return None
    out = []
    for part in str(entry).strip().strip("()").split(";"):
        try:
            out.append(int(part))
        except ValueError:
            out.append(None)
    return out


def format_tree(result: Dict, with_quality: bool = True) -> str:
    """Render an upstream tree with pedigree flags and a summary of how
    much of the result passes through weak (4 or 5) or unscored links."""
    total = result.get("total", 0.0) or 0.0
    unit = result.get("unit", "")
    root = result.get("root", {})

    rows = []   # (prefix+name, share, entry, flags)

    def has_scores(n, is_root=True):
        if not is_root and _scores(n.get("dq_entry")) is not None:
            return True
        return any(has_scores(k, False) for k in n.get("children", []))

    # With no scores anywhere, flagging every line says nothing useful
    per_line = with_quality and has_scores(root)

    def label(n):
        loc = n.get("location")
        return n.get("name", "?") + (f" [{loc}]" if loc else "")

    def flags_of(n, is_root):
        if not per_line or is_root:
            return ""
        sc = _scores(n.get("dq_entry"))
        if sc is None:
            return "! no pedigree"
        names = n.get("dq_indicators") or []
        weak = [f"{(names[i] if i < len(names) else f'indicator {i + 1}').lower()} {v}"
                for i, v in enumerate(sc) if v is not None and v >= 4]
        return ("! " + ", ".join(weak)) if weak else ""

    def walk(n, prefix, child_prefix, is_root):
        rows.append((prefix + label(n), n.get("share", 0.0),
                     (n.get("dq_entry") or ("" if is_root else "n.a."))
                     if per_line else "",
                     flags_of(n, is_root)))
        kids = list(n.get("children", []))
        other = n.get("other")
        items = kids + ([("other", other)] if other else [])
        for k, item in enumerate(items):
            last = k == len(items) - 1
            branch = child_prefix + ("`-- " if last else "+-- ")
            cont = child_prefix + ("    " if last else "|   ")
            if isinstance(item, tuple):
                o = item[1]
                rows.append((branch + f"Other ({o['count']})", o.get("share", 0.0), "", ""))
            else:
                walk(item, branch, cont, False)

    walk(root, "", "", True)

    width = min(max(len(r[0]) for r in rows), 70)
    lines = [f"  {result.get('category', '?')}: {total:.6g} {unit}  "
             f"({result.get('system', '?')}, {result.get('method', '?')})", ""]
    for name, share, entry, flags in rows:
        name = name if len(name) <= width else name[:width - 3] + "..."
        line = f"  {name:<{width}}  {share:6.1f}%"
        if with_quality and entry:
            line += f"  {entry}"
        if flags:
            line += f"  {flags}"
        lines.append(line.rstrip())

    if not with_quality:
        return "\n".join(lines)

    # Summary: share of the result passing through at least one weak link
    # per indicator, counting each branch once (a weak parent covers its
    # children), and the same for links with no scores.
    weak_share: Dict[str, float] = {}
    order: List[str] = []
    unscored = 0.0
    any_scores = False

    def summarise(n, weak_above: set, unscored_above: bool, is_root: bool):
        nonlocal unscored, any_scores
        weak_here = set(weak_above)
        unscored_here = unscored_above
        if not is_root:
            sc = _scores(n.get("dq_entry"))
            if sc is None:
                if not unscored_above:
                    unscored += n.get("share", 0.0)
                unscored_here = True
            else:
                any_scores = True
                names = n.get("dq_indicators") or []
                for i, v in enumerate(sc):
                    name = names[i] if i < len(names) else f"Indicator {i + 1}"
                    if name not in order:
                        order.append(name)
                    if v is not None and v >= 4 and name not in weak_above:
                        weak_share[name] = weak_share.get(name, 0.0) + n.get("share", 0.0)
                        weak_here.add(name)
        for k in n.get("children", []):
            summarise(k, weak_here, unscored_here, False)

    summarise(root, set(), False, True)
    lines.append("")
    if not any_scores:
        lines.append("  No pedigree scores on any branch shown, so data "
                     "quality can't be assessed from this tree.")
        return "\n".join(lines)
    else:
        lines.append("  Weak data (score 4 or 5) on the path to the result, "
                     "in the branches shown:")
        w = max(len(n) for n in order)
        for name in order:
            lines.append(f"    {name:<{w}}  {weak_share.get(name, 0.0):5.1f}%")
    if unscored:
        lines.append(f"  No pedigree scores:  {unscored:5.1f}%")
    return "\n".join(lines)


# ── result queries (RESULT ...) ──────────────────────────────

_QUERY_HEADERS = {
    "category": "Impact category", "amount": "Amount", "unit": "Unit",
    "process": "Process", "location": "Location", "product": "Product",
    "flow": "Flow", "compartment": "Compartment", "direction": "Direction",
    "share_pct": "Share", "factor": "Factor", "factor_unit": "Unit",
    "group": "Group", "tag": "Tag", "level": "Level", "direct": "Direct",
    "system": "System", "currency": "Currency", "index": "No.",
}
_QUERY_WIDTHS = {"category": 50, "process": 60, "flow": 40,
                 "compartment": 40, "product": 40, "unit": 24,
                 "factor_unit": 30, "group": 30, "tag": 30}


def format_number(value) -> str:
    """A number the way impact tables show it."""
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if value == 0:
        return "0"
    if abs(value) > 1e6 or abs(value) < 0.01:
        return f"{value:.4e}"
    return f"{value:.6f}"


def _query_cell(column: str, row: Dict) -> str:
    value = row.get(column)
    if column == "share_pct":
        return "" if value is None else f"{value:.2f}%"
    if column == "level":
        return str(value)
    if column == "process" and "level" in row:
        return "  " * int(row.get("level") or 0) + str(value or "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return format_number(value)
    return "" if value is None else str(value)


def format_query(result: Dict) -> str:
    """One RESULT query as a table with its heading."""
    lines = [f"  {result.get('title', result.get('query', 'Result'))}"]
    context = [f"System: {result.get('system', '?')}"]
    if result.get("method"):
        context.append(f"Method: {result['method']}")
    lines.append("  " + "   ".join(context))
    if result.get("total") is not None and result.get("query") != "costs":
        unit = result.get("unit") or result.get("currency") or ""
        lines.append(f"  Total: {format_number(result['total'])} {unit}".rstrip())
    elif result.get("currency"):
        lines.append(f"  Currency: {result['currency']}")
    rows = result.get("rows", [])
    columns = [c for c in result.get("columns", [])]
    if not rows:
        lines.append("  (nothing to show)")
    else:
        headers = [_QUERY_HEADERS.get(c, c.replace("_", " ").capitalize())
                   for c in columns]
        table = [[_query_cell(c, row) for c in columns] for row in rows]
        lines.append("")
        lines.append(format_table(
            headers, table,
            max_widths=[_QUERY_WIDTHS.get(c, 18) for c in columns]))
    shown, total = len(rows), result.get("row_count", len(rows))
    if result.get("top") and total > shown:
        lines.append(f"  Showing {shown} of {total} rows (TOP "
                     f"{result['top']}).")
    if result.get("note"):
        lines.append(f"  {result['note']}")
    return "\n".join(lines)


def query_to_csv(result: Dict) -> str:
    """One RESULT query as CSV: a header row, then the rows."""
    output = io.StringIO()
    writer = csv.writer(output)
    columns = list(result.get("columns", []))
    writer.writerow(columns)
    for row in result.get("rows", []):
        writer.writerow(["" if row.get(c) is None else row.get(c)
                         for c in columns])
    return output.getvalue()


# ── the wider fields of a process and a system (SHOW ...) ────

_DOC_LABELS = {
    "completeness_description": "COMPLETENESS",
    "compliance_declarations": "COMPLIANCE",
    "creation_date": "CREATED",
    "data_collection_description": "DATA COLLECTION",
    "data_documentor": "DOCUMENTOR",
    "data_generator": "GENERATOR",
    "data_selection_description": "DATA SELECTION",
    "data_set_owner": "OWNER",
    "data_treatment_description": "DATA TREATMENT",
    "flow_completeness": "FLOW COMPLETENESS",
    "geography_description": "GEOGRAPHY",
    "intended_application": "INTENDED APPLICATION",
    "inventory_method_description": "INVENTORY METHOD",
    "is_copyright_protected": "COPYRIGHT",
    "modeling_constants_description": "MODELLING CONSTANTS",
    "project_description": "PROJECT",
    "publication": "PUBLICATION",
    "restrictions_description": "RESTRICTIONS",
    "reviews": "REVIEW",
    "sampling_description": "SAMPLING",
    "sources": "SOURCE",
    "technology_description": "TECHNOLOGY",
    "time_description": "TIME",
    "use_advice": "USE ADVICE",
    "valid_from": "VALID FROM",
    "valid_until": "VALID UNTIL",
}


def _document_lines(document: Dict) -> List[str]:
    lines = []
    for field_name, label in _DOC_LABELS.items():
        if field_name not in document:
            continue
        value = document[field_name]
        if field_name == "is_copyright_protected":
            lines.append(f"    {label} {'YES' if value else 'NO'}")
        elif field_name == "sources":
            lines.extend(f"    {label} \"{v}\"" for v in value)
        elif field_name == "flow_completeness":
            lines.extend(f"    {label} \"{a['aspect']}\" \"{a['value']}\""
                         for a in value)
        elif field_name == "reviews":
            for r in value:
                text = f"    {label} \"{r['type']}\""
                text += "".join(f" REVIEWER \"{a}\"" for a in r["reviewers"])
                if r["details"]:
                    text += f" DETAILS \"{r['details']}\""
                if r["report"]:
                    text += f" REPORT \"{r['report']}\""
                for sc in r["scopes"]:
                    text += f" SCOPE \"{sc['name']}\""
                    text += "".join(f" METHOD \"{m}\"" for m in sc["methods"])
                text += "".join(f" ASSESSMENT \"{a['aspect']}\" "
                                f"\"{a['value']}\"" for a in r["assessment"])
                lines.append(text)
        elif field_name == "compliance_declarations":
            for c in value:
                text = f"    {label} \"{c['system']}\""
                if c["comment"]:
                    text += f" COMMENT \"{c['comment']}\""
                text += "".join(f" ASPECT \"{a['aspect']}\" "
                                f"\"{a['value']}\"" for a in c["aspects"])
                lines.append(text)
        else:
            lines.append(f"    {label} \"{value}\"")
    return lines


def process_extras_summary(fields: Dict) -> str:
    """One line saying which of the wider fields a process carries,
    or '' if it has none."""
    ex = fields.get("exchanges", [])
    parts = []
    n = sum(1 for e in ex if e.get("uncertainty"))
    n += len(fields.get("parameters") or {})
    if n:
        parts.append(f"uncertainty on {n} amount{'s' if n != 1 else ''}")
    n = sum(1 for e in ex if e.get("cost"))
    if n:
        parts.append(f"{n} cost{'s' if n != 1 else ''}")
    n = sum(1 for e in ex if e.get("avoided"))
    if n:
        parts.append(f"{n} avoided product{'s' if n != 1 else ''}")
    n = sum(1 for e in ex if e.get("site"))
    if n:
        parts.append(f"{n} exchange site{'s' if n != 1 else ''}")
    if fields.get("allocation"):
        parts.append("allocation factors ("
                     + ", ".join(k.lower() for k in fields["allocation"]) + ")")
    if fields.get("document"):
        n = len(fields["document"])
        parts.append(f"{n} documentation field{'s' if n != 1 else ''}")
    if fields.get("social"):
        n = len(fields["social"])
        parts.append(f"{n} social aspect{'s' if n != 1 else ''}")
    if fields.get("type") == "LCI RESULT":
        parts.append("type LCI RESULT")
    if fields.get("infrastructure"):
        parts.append("infrastructure process")
    return ", ".join(parts)


def format_process_fields(fields: Dict, part: str = "FIELDS") -> str:
    """SHOW PROCESS "x" FIELDS | DOCUMENT | ALLOCATION | SOCIAL."""
    name = fields.get("process_name", "?")
    lines = []
    part = (part or "FIELDS").upper()
    everything = part == "FIELDS"
    if everything:
        lines.append(f"  {name}")
        lines.append(f"    TYPE {fields.get('type', 'UNIT')}"
                     + ("   INFRASTRUCTURE" if fields.get("infrastructure")
                        else ""))
        if fields.get("default_allocation"):
            lines.append(f"    DEFAULT ALLOCATION "
                         f"{fields['default_allocation']}")
        if fields.get("process_pedigree"):
            lines.append(f"    PROCESS PEDIGREE {fields['process_pedigree']}")
        rows = []
        for e in fields.get("exchanges", []):
            notes = []
            if e.get("avoided"):
                notes.append("AVOIDED")
            if e.get("uncertainty"):
                notes.append("UNCERTAINTY " + e["uncertainty"]["text"])
            if e.get("base_uncertainty") is not None:
                notes.append(f"BASE UNCERTAINTY {e['base_uncertainty']:g}")
            if e.get("cost"):
                c = e["cost"]
                shown = (f"FORMULA \"{c['formula']}\"" if c.get("formula")
                         else format_number(c.get("value") or 0.0))
                notes.append(f"COST {shown} CURRENCY \"{c['currency']}\"")
            if e.get("site"):
                notes.append(f"SITE \"{e['site']}\"")
            if notes:
                rows.append([("INPUT" if e["is_input"] else "OUTPUT"),
                             e["flow"], "  ".join(notes)])
        if rows:
            lines.append("")
            lines.append(format_table(["", "Exchange", "Set on it"], rows,
                                      max_widths=[6, 45, 80]))
        for pname, unc in (fields.get("parameters") or {}).items():
            lines.append(f"    LET {pname} UNCERTAINTY {unc['text']}")
    if everything or part == "ALLOCATION":
        allocation = fields.get("allocation") or {}
        if not allocation and not everything:
            lines.append(f"  {name}: no allocation factors")
        for kind, factors in allocation.items():
            lines.append(f"    ALLOCATION {kind}")
            for f in factors:
                share = (f"FORMULA \"{f['formula']}\"" if f.get("formula")
                         else f"{f['value']:g}")
                tail = f" FOR \"{f['exchange']}\"" if f.get("exchange") else ""
                lines.append(f"      \"{f['product']}\", {share}{tail}")
            lines.append("    END ALLOCATION")
    if everything or part == "DOCUMENT":
        doc = _document_lines(fields.get("document") or {})
        if doc:
            lines.append("    DOCUMENT")
            lines.extend("  " + d for d in doc)
            lines.append("    END DOCUMENT")
        elif not everything:
            lines.append(f"  {name}: no documentation fields are set")
    if everything or part == "SOCIAL":
        social = fields.get("social") or []
        if not social and not everything:
            lines.append(f"  {name}: no social aspects")
        if fields.get("social_schema"):
            lines.append(f"    SOCIAL SCHEMA \"{fields['social_schema']}\"")
        for a in social:
            text = (f"    SOCIAL \"{a['indicator']}\", \"{a['raw']}\", "
                    f"{a['risk'].replace('_', ' ')}")
            if a.get("activity") is not None:
                text += f" ACTIVITY {a['activity']:g}"
            if a.get("comment"):
                text += f" COMMENT \"{a['comment']}\""
            if a.get("source"):
                text += f" SOURCE \"{a['source']}\""
            if a.get("quality"):
                text += f" QUALITY \"{a['quality']}\""
            lines.append(text)
    return "\n".join(lines)


def format_system_fields(fields: Dict, part: str = "") -> str:
    """SHOW SYSTEM "x" SETS | GROUPS."""
    name = fields.get("system", "?")
    lines = []
    part = (part or "").upper()
    if part in ("", "SETS"):
        sets = fields.get("parameter_sets") or []
        if not sets:
            lines.append(f"  {name}: no parameter sets")
        for s in sets:
            lines.append(f"    PARAMETER SET \"{s['name']}\""
                         + (" BASELINE" if s["baseline"] else ""))
            for v in s["values"]:
                tail = f" IN PROCESS \"{v['process']}\"" if v["process"] else ""
                lines.append(f"      {v['name']} = {v['value']:g}{tail}")
            lines.append("    END PARAMETER SET")
    if part in ("", "GROUPS"):
        groups = fields.get("analysis_groups") or []
        if not groups:
            lines.append(f"  {name}: no analysis groups")
        for g in groups:
            lines.append(f"    ANALYSIS GROUP \"{g['name']}\"")
            lines.extend(f"      \"{p}\"" for p in g["processes"])
            lines.append("    END ANALYSIS GROUP")
    return "\n".join(lines)
