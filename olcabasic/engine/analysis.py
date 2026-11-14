"""
Many calculations on one product system: scenarios and sensitivity,
from values or from CSV files.

Part of olcabasic.engine.Engine (see engine.py).
"""

from olca_ipc import Client
import olca_schema as o
from typing import Dict, List, Optional, Any
import logging
import time
import csv
import os
import uuid
import urllib.request
import urllib.parse
import json as json_module
import re
import threading

# One logger for the whole engine, under the name it has always had.
logger = logging.getLogger("olcabasic.engine.engine")

from .validators import (
    validate_category as _validate_category,
    validate_param_name as _validate_param_name,
    validate_formula as _validate_formula,
    validate_uuid as _validate_uuid,
)


class AnalysisMixin:
    """Many calculations on one product system: scenarios and sensitivity,"""

    def run_scenarios(self, system_ref: str, method_ref: str,
                      scenarios: Dict[str, Dict[str, float]],
                      allocation: Optional[str] = None) -> Dict:
        """
        Run scenario calculations.

        scenarios: {scenario_name: {param_name: value, ...}, ...}

        Uses the same ParameterRedef + CalculationSetup pattern as
        B280_olca_scenarios.py.
        """
        # V08: Reject empty scenarios
        if not scenarios:
            return {
                "error": "At least one scenario is required. "
                         "Pass scenarios as {name: {param: value, ...}, ...}."
            }

        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        # Every copy of every parameter, so a name shared by several
        # processes is changed everywhere, not just in one of them
        all_names = set()
        for param_values in scenarios.values():
            all_names.update(param_values.keys())
        targets = self._parameter_targets(system, all_names)

        # B10: Collect all unique parameter names across scenarios
        # and warn about any that don't exist in the system
        all_scenario_params = set()
        for param_values in scenarios.values():
            all_scenario_params.update(param_values.keys())
        split = self._split_targets(targets, sorted(all_scenario_params))
        missing_params = split["missing"]
        dependent_params = split["dependent"]
        usable = set(split["ok"])
        # A scenario that names a parameter the system does not have
        # would run as the baseline under another name: refused.
        if missing_params:
            which = sorted(n for s, v in scenarios.items() for n in v
                           if n in missing_params)
            return {"error": f"The system '{system.name}' has no input "
                             f"parameter called "
                             f"{', '.join(repr(n) for n in sorted(set(which))[:10])}"
                             f", so the scenarios were not run.",
                    "hint": "SHOW SYSTEM \"name\" PARAMS lists the "
                            "parameters it has."}
        if dependent_params:
            return {"error": f"{', '.join(repr(n) for n in dependent_params[:10])} "
                             f"{'is' if len(dependent_params) == 1 else 'are'} "
                             f"calculated from a formula and cannot be set "
                             f"in a scenario, so the scenarios were not run.",
                    "hint": "Set the input parameters the formula uses."}

        results = {}
        for scenario_name, param_values in scenarios.items():
            logger.info(f"Running scenario: {scenario_name}")

            param_redefs = [
                o.ParameterRedef(
                    name=name,
                    value=float(value),
                    context=copy["context"],
                )
                for name, value in param_values.items()
                if name in usable
                for copy in targets[name]
                if copy["is_input"]
            ]

            setup = o.CalculationSetup(
                target=system,
                impact_method=method,
                parameters=param_redefs,
                allocation=self._resolve_allocation(allocation),
            )
            result = self.client.calculate(setup)
            result.wait_until_ready()

            try:
                impacts = result.get_total_impacts()
                results[scenario_name] = self._impacts_to_list(impacts)
            finally:
                result.dispose()

        result = {
            "system": system.name,
            "method": method.name,
            "scenario_count": len(results),
            "results": results,
        }
        shared = {n: len([c for c in targets[n] if c["is_input"]])
                  for n in usable
                  if len([c for c in targets[n] if c["is_input"]]) > 1}
        if shared:
            result["shared_parameters"] = shared
        warnings = []
        if missing_params:
            result["missing"] = missing_params
            warnings.append(
                f"{len(missing_params)} parameter(s) not found in "
                f"system and were ignored: {', '.join(missing_params[:10])}"
            )
        if dependent_params:
            result["dependent"] = dependent_params
            warnings.append(
                f"{len(dependent_params)} parameter(s) are calculated "
                f"from formulas and can't be set directly; change the "
                f"input parameters they depend on instead: "
                f"{', '.join(dependent_params[:10])}"
            )
        if warnings:
            result["warning"] = ". ".join(warnings)
        return result

    def run_parameter_sets(self, system_ref: str, method_ref: str,
                           allocation: Optional[str] = None,
                           names: Optional[List[str]] = None) -> Dict:
        """
        Run the parameter sets stored on a product system (openLCA's
        own scenarios), one calculation each. names limits the run to
        some of them. The result has the shape of run_scenarios.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}
        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}
        full = self.client.get(o.ProductSystem, system.id)
        sets = list(getattr(full, "parameter_sets", None) or [])
        if not sets:
            return {"error": f"'{system.name}' has no parameter sets stored "
                             f"on it. Add them with EDIT SYSTEM ... "
                             f"PARAMETER SET \"name\" ... END PARAMETER SET."}
        if names:
            known = {s.name for s in sets}
            missing = [n for n in names if n not in known]
            if missing:
                return {"error": f"'{system.name}' has no parameter set "
                                 f"called: {', '.join(missing)}. Its sets: "
                                 f"{', '.join(sorted(known))}."}
            sets = [s for s in sets if s.name in names]
        results = {}
        for s in sets:
            setup = o.CalculationSetup(
                target=system, impact_method=method,
                parameters=list(s.parameters or []),
                allocation=self._resolve_allocation(allocation))
            result = self.client.calculate(setup)
            result.wait_until_ready()
            try:
                results[s.name] = self._impacts_to_list(
                    result.get_total_impacts())
            finally:
                result.dispose()
        return {"system": system.name, "method": method.name,
                "scenario_count": len(results), "results": results,
                "baseline": next((s.name for s in sets if s.is_baseline), "")}

    # ── CSV-based scenarios (mirrors B280_olca_scenarios.py) ──

    def read_scenarios_csv(self, csv_path: str) -> Dict:
        """
        Read a scenarios CSV file.

        Expected format: first column 'Parameter', remaining columns
        are scenario names. Each row holds the parameter value per
        scenario. Same format as B280_olca_scenarios.py expects.
        """
        if not os.path.exists(csv_path):
            return {"error": f"File not found: {csv_path}"}

        try:
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                rows = list(reader)

            if not fieldnames or "Parameter" not in fieldnames:
                return {"error": "CSV must have 'Parameter' as first column"}

            scenario_names = [col for col in fieldnames if col != "Parameter"]
            parameter_names = [row["Parameter"] for row in rows]

            # Convert to the dict format run_scenarios expects
            scenarios = {}
            for name in scenario_names:
                scenarios[name] = {}
                for row in rows:
                    raw = row[name].strip().replace(",", ".")
                    try:
                        scenarios[name][row["Parameter"]] = float(raw)
                    except (ValueError, TypeError):
                        return {
                            "error": (
                                f"Cannot parse value '{row[name]}' for "
                                f"parameter '{row['Parameter']}' in "
                                f"scenario '{name}' as a number"
                            ),
                        }

            return {
                "csv_path": csv_path,
                "scenario_names": scenario_names,
                "parameter_names": parameter_names,
                "scenario_count": len(scenario_names),
                "parameter_count": len(parameter_names),
                "scenarios": scenarios,
            }
        except Exception as e:
            return {"error": f"Failed to read CSV: {e}"}

    def run_scenarios_csv(self, system_ref: str, method_ref: str,
                          csv_path: str,
                          output_path: str = "",
                          allocation: Optional[str] = None) -> Dict:
        """
        Full scenario pipeline: read CSV, calculate, write results.

        If output_path is empty, generates one from the method name.
        Returns the calculation results and the output file path.
        """
        # Read the CSV
        csv_data = self.read_scenarios_csv(csv_path)
        if "error" in csv_data:
            return csv_data

        # Resolve system and method
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        # Run the scenarios
        calc_result = self.run_scenarios(
            system_ref, method_ref, csv_data["scenarios"],
            allocation=allocation
        )
        if "error" in calc_result:
            return calc_result

        # Write results CSV - default to same folder as input
        if not output_path:
            input_dir = os.path.dirname(os.path.abspath(csv_path))
            safe_name = method.name.replace(" ", "_").replace("/", "_")
            output_path = os.path.join(
                input_dir, f"scenario_results_{safe_name}.csv"
            )

        scenario_names = csv_data["scenario_names"]
        results = calc_result["results"]

        try:
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)

                # Header
                writer.writerow(["Impact Category"] + scenario_names)

                # Use the first scenario's results as the category template
                first = results[scenario_names[0]]

                # Build lookup: {scenario: {category_id: amount}}
                by_scenario = {}
                for sname in scenario_names:
                    by_scenario[sname] = {
                        imp["category_id"]: imp["amount"]
                        for imp in results[sname]
                    }

                # One row per impact category
                for impact in first:
                    cat_name = impact["category"]
                    unit = impact["unit"]
                    cat_id = impact["category_id"]

                    row = [f"{cat_name} ({unit})"]
                    for sname in scenario_names:
                        row.append(by_scenario[sname].get(cat_id, "N/A"))
                    writer.writerow(row)

            calc_result["output_file"] = os.path.abspath(output_path)
            calc_result["csv_input"] = csv_path
            return calc_result

        except Exception as e:
            calc_result["output_error"] = str(e)
            return calc_result

    def run_sensitivity(self, system_ref: str, method_ref: str,
                        parameter_names: List[str],
                        variation_pct: float = 20.0,
                        allocation: Optional[str] = None) -> Dict:
        """
        Run +/- sensitivity analysis on named parameters.

        Uses the same ParameterRedef pattern as B280_olca_sensitivity.py.
        Each parameter is varied independently; all others stay at baseline.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        # W03: Sanity-check variation percentage
        if variation_pct <= 0:
            return {"error": "variation_pct must be positive."}
        if variation_pct >= 100:
            return {
                "error": f"A variation of {variation_pct:g}% takes each "
                         f"parameter down to zero or below. Use less than "
                         f"100%.",
            }
        sensitivity_warnings = []

        # Every copy of every parameter (see _parameter_targets)
        targets = self._parameter_targets(system, set(parameter_names))
        split = self._split_targets(targets, parameter_names)
        testable = split["ok"]
        missing = split["missing"]
        dependent = split["dependent"]

        if not testable:
            return {
                "error": "No matching input parameters found in system",
                "missing": missing,
                "dependent": dependent,
            }
        if missing:
            return {"error": f"The system '{system.name}' has no input "
                             f"parameter called "
                             f"{', '.join(repr(n) for n in missing[:10])}; "
                             f"nothing was varied.",
                    "missing": missing, "dependent": dependent}

        variation_factor = variation_pct / 100.0

        # Baseline calculation
        logger.info("Running baseline calculation")
        alloc = self._resolve_allocation(allocation)
        setup = o.CalculationSetup(
            target=system, impact_method=method, allocation=alloc)
        result = self.client.calculate(setup)
        result.wait_until_ready()

        try:
            baseline_impacts = result.get_total_impacts()
            baseline = {}
            for i in baseline_impacts:
                baseline[i.impact_category.name] = {
                    "amount": i.amount,
                    "unit": getattr(i.impact_category, "ref_unit", ""),
                }
        finally:
            result.dispose()

        # Sensitivity runs
        sensitivity = {}
        for param_name in testable:
            copies = [c for c in targets[param_name] if c["is_input"]]
            baseline_value = copies[0]["value"]
            logger.info(f"Varying: {param_name} (baseline: {baseline_value}, "
                        f"{len(copies)} cop{'y' if len(copies) == 1 else 'ies'})")

            sensitivity[param_name] = {"baseline_value": baseline_value}
            if len(copies) > 1:
                sensitivity[param_name]["copies"] = len(copies)
                values = [c["value"] for c in copies]
                if len(set(values)) > 1:
                    sensitivity[param_name]["baseline_values"] = values

            for label, multiplier in [("minus", 1 - variation_factor),
                                      ("plus", 1 + variation_factor)]:
                # Each copy moves by the same percentage from its own
                # baseline, so the whole model is varied consistently
                param_redefs = [
                    o.ParameterRedef(
                        name=param_name,
                        value=c["value"] * multiplier,
                        context=c["context"],
                    )
                    for c in copies
                ]
                setup = o.CalculationSetup(
                    target=system,
                    impact_method=method,
                    parameters=param_redefs,
                    allocation=alloc,
                )
                result = self.client.calculate(setup)
                result.wait_until_ready()

                try:
                    impacts = result.get_total_impacts()
                    sensitivity[param_name][label] = {
                        i.impact_category.name: i.amount for i in impacts
                    }
                finally:
                    result.dispose()

        result = {
            "system": system.name,
            "method": method.name,
            "variation_pct": variation_pct,
            "baseline": baseline,
            "sensitivity": sensitivity,
            "tested": testable,
            "missing": missing,
        }
        if dependent:
            result["dependent"] = dependent
            sensitivity_warnings.append(
                f"Skipped formula (dependent) parameters, which can't be "
                f"varied directly: {', '.join(dependent)}")
        if sensitivity_warnings:
            result["warnings"] = sensitivity_warnings
        return result

    # ── CSV-based sensitivity (mirrors B280_olca_sensitivity.py) ─

    def read_sensitivity_csv(self, csv_path: str) -> Dict:
        """
        Read a sensitivity CSV file.

        Expected format: one parameter name per line.
        Lines starting with '#' are comments. A header row of
        'Parameter' is skipped. Same format as B280_olca_sensitivity.py.
        """
        if not os.path.exists(csv_path):
            return {"error": f"File not found: {csv_path}"}

        try:
            names = []
            with open(csv_path, "r") as f:
                for line in f:
                    name = line.strip()
                    if not name or name.startswith("#"):
                        continue
                    if name == "Parameter":
                        continue
                    names.append(name)

            return {
                "csv_path": csv_path,
                "parameter_count": len(names),
                "parameters": names,
            }
        except Exception as e:
            return {"error": f"Failed to read CSV: {e}"}

    def run_sensitivity_csv(self, system_ref: str, method_ref: str,
                            csv_path: str, variation_pct: float = 20.0,
                            output_path: str = "",
                            allocation: Optional[str] = None) -> Dict:
        """
        Full sensitivity pipeline: read CSV, calculate, write results.

        Output CSV matches the B280_olca_sensitivity.py format:
        Impact Category | Unit | Baseline | param1 -X% | param1 +X% | ...
        """
        # Read the parameter list
        csv_data = self.read_sensitivity_csv(csv_path)
        if "error" in csv_data:
            return csv_data

        parameter_names = csv_data["parameters"]

        # Run sensitivity
        calc_result = self.run_sensitivity(
            system_ref, method_ref, parameter_names, variation_pct,
            allocation=allocation
        )
        if "error" in calc_result:
            return calc_result

        # Write results CSV - default to same folder as input
        if not output_path:
            input_dir = os.path.dirname(os.path.abspath(csv_path))
            method = self._resolve_method(method_ref)
            safe_name = method.name.replace(" ", "_").replace("/", "_")
            output_path = os.path.join(
                input_dir, f"sensitivity_results_{safe_name}.csv"
            )

        baseline = calc_result["baseline"]
        sensitivity = calc_result["sensitivity"]
        testable = calc_result["tested"]

        try:
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)

                # Header: Impact Category | Unit | Baseline | p1 -X% | p1 +X% | ...
                header = ["Impact Category", "Unit", "Baseline"]
                for pname in testable:
                    header.append(f"{pname} -{variation_pct}%")
                    header.append(f"{pname} +{variation_pct}%")
                writer.writerow(header)

                # One row per impact category
                for cat_name, cat_data in baseline.items():
                    row = [cat_name, cat_data["unit"], cat_data["amount"]]

                    for pname in testable:
                        minus_val = sensitivity[pname]["minus"].get(cat_name, "N/A")
                        plus_val = sensitivity[pname]["plus"].get(cat_name, "N/A")
                        row.append(minus_val)
                        row.append(plus_val)

                    writer.writerow(row)

            calc_result["output_file"] = os.path.abspath(output_path)
            calc_result["csv_input"] = csv_path
            return calc_result

        except Exception as e:
            calc_result["output_error"] = str(e)
            return calc_result
