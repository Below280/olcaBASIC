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
    headers = ["Name", "Category"]
    rows = [[p.get("name", "?"), p.get("category", "")] for p in procs]

    count = results.get("count", len(procs))
    total = results.get("total_matches", count)
    lines = [f"  {count} results (of {total} total)"]
    if rows:
        lines.append(format_table(headers, rows, max_widths=[70, 70]))
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
        for ex in exchanges:
            direction = "INPUT" if ex.get("is_input") else "OUTPUT"
            qref = "*" if ex.get("is_qref") else ""
            amt = ex.get("amount", 0)
            formula = ex.get("formula")
            amt_str = formula if formula else (
                f"{amt:.4e}" if abs(amt) > 1e4 else f"{amt:.6g}")
            rows.append([
                direction,
                ex.get("flow", "?"),
                amt_str,
                ex.get("unit", ""),
                qref,
                ex.get("provider", "") or "",
            ])
        lines.append(format_table(headers, rows, max_widths=[8, 45, 15, 8, 4, 30]))

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
