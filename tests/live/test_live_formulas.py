"""
Live test: an amount olcaBASIC writes as an openLCA formula comes out
in openLCA as olcaBASIC works it out itself.

On openLCA 2.7.0 (14/11/2026) sqr(x) is x squared, log is base 10, int
cuts towards zero, round takes halves up, the values of a function are
separated by ;, and a formula openLCA cannot read leaves the old amount
in place without an error. olcaBASIC renames and rewrites for that;
this test calculates each case in openLCA and compares.

The system and the process are deleted at the end; the flows and the
global parameter stay and are reused by the next run.
"""

import olca_schema as o
import pytest

pytestmark = pytest.mark.live

FOLDER = "00: olcaBASIC live formulas"
NAME = "olcaBASIC live formulas product"
X = "olcabasic_live_formula_x"
CASES = {
    "sqr": f"SQR({X})", "log": f"LOG({X})", "int": f"INT(-{X} / 3)",
    "min": f"MIN({X}, 2)", "max": f"MAX({X}, 9)",
    "round": f"ROUND({X} / 8)", "power": f"-{X} ^ 2",
    "nested": f"ABS(SQR({X}) - EXP(1)) * {X}",
}


def flow(key):
    return f"olcaBASIC live formula {key}"


def test_formulas_come_out_in_openlca_as_in_olcabasic(runner):
    lines = "\n".join(f'  OUTPUT MAKE FLOW "{flow(k)}", {v}, kg TO AIR'
                      for k, v in CASES.items())
    expected = {}
    s = runner.session
    try:
        r = s.run(f'SET PROCESS FOLDER "{FOLDER}"\nSET FLOW FOLDER '
                  f'"{FOLDER}"\nLET {X} = 4\n'
                  f'MAKE PROCESS "{NAME}"\n  OUTPUT MAKE FLOW "{NAME}", 1, '
                  f'kg, PRODUCT\n{lines}\nEND PROCESS\nSYSTEM "{NAME}"\n'
                  + "\n".join(f"PRINT {v}" for v in CASES.values()))
        assert r.ok, r.errors
        printed = [float(t) for t in r.text.splitlines()[-len(CASES):]]
        expected = dict(zip(CASES, printed))
        client = s.client
        system = next(d for d in client.get_descriptors(o.ProductSystem)
                      if d.name == NAME)
        result = client.calculate(o.CalculationSetup(
            target=o.Ref(id=system.id, ref_type=o.RefType.ProductSystem)))
        result.wait_until_ready()
        got = {}
        for v in result.get_total_flows():
            name = v.envi_flow.flow.name
            for k in CASES:
                if name == flow(k):
                    got[k] = v.amount
        result.dispose()
        for k in CASES:
            assert got.get(k) == pytest.approx(expected[k], rel=1e-9), \
                f"{k}: {CASES[k]} is {expected[k]} in olcaBASIC, " \
                f"{got.get(k)} in openLCA"
    finally:
        s.run(f'CONFIRM DELETE ON\nDELETE SYSTEM "{NAME}"\n'
              f'DELETE PROCESS "{NAME}"\n'
              + "\n".join(f'DELETE FLOW "{flow(k)}"' for k in CASES))
