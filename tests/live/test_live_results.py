"""
Live tests: every RESULT query against the reference model.

    pytest -m live

One calculation, then one question after another on the open result.
The checks are the identities that must hold for any model: direct
contributions add up to the total, a tree's branches and its own direct
part add up to its root, the reference process at a demand of one unit
has an intensity equal to the totals, and so on. Totals are compared
with the private baseline.

Nothing here names a dataset: the model comes from the baseline file,
which is not in the repository.
"""

import pytest

from test_live_baseline import close

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def calc(live, baseline, names):
    """The reference model, calculated once and left open."""
    method = next(iter(baseline["calculate"]))
    got = live.run(f'CALCULATE "{names["name"]}" USING "{method}"')
    yield {"live": live, "method": method, "calculate": got,
           "want": baseline["calculate"][method], "name": names["name"]}
    live.run("CLOSE RESULT ALL")


def q(calc, code):
    return calc["live"].run(code)


@pytest.fixture(scope="module")
def category(calc):
    """A category with a total that is not zero, and that total."""
    for imp in calc["calculate"]["impacts"]:
        if abs(imp["amount"]) > 1e-12:
            return imp["category"], imp["amount"]
    pytest.skip("every impact total of the reference model is zero")


@pytest.fixture(scope="module")
def flow(calc):
    """The largest elementary flow of the inventory: its row."""
    rows = q(calc, "RESULT FLOWS TOP 1")["rows"]
    assert rows
    return rows[0]


def near(a, b, tol=1e-6):
    return close(a, b, tol) or abs(a - b) < 1e-15


def test_the_result_is_open_and_only_one(calc):
    session = calc["live"].session
    assert session.open_results == [""]
    assert len(session.engine.open_results()) == 1


def test_impacts_match_the_baseline(calc, tol):
    got = {r["category"]: r for r in q(calc, "RESULT IMPACTS")["rows"]}
    want = {i["category"]: i for i in calc["want"]["impacts"]}
    assert set(got) == set(want)
    for cat, w in want.items():
        assert close(got[cat]["amount"], w["amount"], tol), cat
        assert got[cat]["unit"] == w["unit"]


def test_one_category(calc, category):
    name, total = category
    rows = q(calc, f'RESULT IMPACTS CATEGORY "{name}"')["rows"]
    assert len(rows) == 1 and near(rows[0]["amount"], total)


def test_categories_processes_demand(calc):
    cats = q(calc, "RESULT CATEGORIES")["rows"]
    assert len(cats) == len(calc["want"]["impacts"])
    procs = q(calc, "RESULT PROCESSES")
    assert procs["row_count"] > 1
    assert any(r["process"] == calc["name"] for r in procs["rows"])
    demand = q(calc, "RESULT DEMAND")["rows"]
    assert demand[0]["process"] == calc["name"]
    assert near(demand[0]["amount"], 1.0)


def test_inventory(calc, flow):
    listed = q(calc, "RESULT FLOWS LIST")
    total = q(calc, "RESULT FLOWS")
    assert listed["row_count"] == total["row_count"] > 0
    one = q(calc, f'RESULT FLOWS FLOW "{flow["flow_id"]}"')["rows"]
    assert near(one[0]["amount"], flow["amount"])


def test_flows_of_the_reference_process(calc, flow):
    """The reference process has no elementary exchanges: its direct
    flows are zero, and with its supply chain it is the whole system."""
    name = calc["name"]
    direct = q(calc, f'RESULT FLOWS OF PROCESS "{name}" DIRECT')["rows"]
    assert all(r["amount"] == 0 for r in direct)
    one = q(calc, f'RESULT FLOWS OF PROCESS "{name}" FLOW "{flow["flow_id"]}"')
    assert near(one["rows"][0]["amount"], flow["amount"])
    one = q(calc, f'RESULT FLOWS OF PROCESS "{name}" DIRECT '
                  f'FLOW "{flow["flow_id"]}"')
    assert one["rows"][0]["amount"] == 0
    whole = q(calc, f'RESULT FLOWS OF PROCESS "{name}" TOP 1')["rows"]
    assert whole[0]["flow_id"] == flow["flow_id"]
    assert near(whole[0]["amount"], flow["amount"])


def test_flow_by_process_adds_up(calc, flow):
    r = q(calc, f'RESULT FLOW "{flow["flow_id"]}" BY PROCESS')
    assert near(r["total"], flow["amount"])
    assert near(sum(row["amount"] for row in r["rows"]), flow["amount"])


def test_direct_contributions_add_up_to_the_total(calc, category):
    name, total = category
    r = q(calc, f'RESULT CONTRIBUTION BY PROCESS DIRECT CATEGORY "{name}"')
    assert near(r["total"], total)
    assert near(sum(row["amount"] for row in r["rows"]), total)
    assert near(sum(row["share_pct"] for row in r["rows"]), 100.0)


def test_contribution_of_the_reference_process(calc, category):
    name, total = category
    me = calc["name"]
    r = q(calc, f'RESULT CONTRIBUTION OF PROCESS "{me}" CATEGORY "{name}"')
    assert near(r["rows"][0]["amount"], total)
    r = q(calc, f'RESULT CONTRIBUTION OF PROCESS "{me}" DIRECT '
                f'CATEGORY "{name}"')
    assert r["rows"][0]["amount"] == 0
    every = q(calc, f'RESULT CONTRIBUTION OF PROCESS "{me}"')["rows"]
    want = {i["category"]: i["amount"] for i in calc["want"]["impacts"]}
    for row in every:
        assert near(row["amount"], want[row["category"]]), row["category"]
    direct = q(calc, f'RESULT CONTRIBUTION OF PROCESS "{me}" DIRECT')["rows"]
    assert all(row["amount"] == 0 for row in direct)


def test_contribution_by_flow_and_factors(calc, category):
    name, total = category
    r = q(calc, f'RESULT CONTRIBUTION BY FLOW CATEGORY "{name}"')
    assert near(sum(row["amount"] for row in r["rows"]), total)
    top = r["rows"][0]
    one = q(calc, f'RESULT CONTRIBUTION BY FLOW CATEGORY "{name}" '
                  f'FLOW "{top["flow_id"]}"')["rows"]
    assert near(one[0]["amount"], top["amount"])
    # a flow's contribution is its amount times its factor
    factor = q(calc, f'RESULT FACTORS CATEGORY "{name}" '
                     f'FLOW "{top["flow_id"]}"')["rows"][0]["factor"]
    amount = q(calc, f'RESULT FLOWS FLOW "{top["flow_id"]}"')["rows"][0]["amount"]
    assert near(factor * amount, top["amount"])
    factors = q(calc, f'RESULT FACTORS CATEGORY "{name}" TOP 5')
    assert factors["rows"] and factors["rows"][0]["factor"] != 0


def test_intensity_of_the_reference_process(calc, category, flow):
    """At a demand of one unit, the reference process's intensity is
    the result itself."""
    name, total = category
    me = calc["name"]
    rows = q(calc, f'RESULT INTENSITY OF PROCESS "{me}"')["rows"]
    want = {i["category"]: i["amount"] for i in calc["want"]["impacts"]}
    assert len(rows) == len(want)
    for row in rows:
        assert near(row["amount"], want[row["category"]]), row["category"]
    one = q(calc, f'RESULT INTENSITY OF PROCESS "{me}" CATEGORY "{name}"')
    assert near(one["rows"][0]["amount"], total)
    flows = q(calc, f'RESULT INTENSITY OF PROCESS "{me}" FLOWS TOP 1')["rows"]
    assert near(flows[0]["amount"], flow["amount"])
    one = q(calc, f'RESULT INTENSITY OF PROCESS "{me}" '
                  f'FLOW "{flow["flow_id"]}"')
    assert near(one["rows"][0]["amount"], flow["amount"])


def test_scaling_requirements_totality(calc):
    me = calc["name"]
    scaling = q(calc, "RESULT SCALING")["rows"]
    mine = next(r for r in scaling if r["process"] == me)
    assert near(mine["amount"], 1.0)
    column = q(calc, f'RESULT SCALING OF PROCESS "{me}"')["rows"]
    assert len(column) == 5            # the product and its four inputs
    own = next(r for r in column if r["process"] == me)
    assert near(own["amount"], 1.0)
    assert all(r["amount"] < 0 for r in column if r["process"] != me)
    unscaled = q(calc, f'RESULT SCALING OF PROCESS "{me}" UNSCALED')["rows"]
    assert sorted(r["amount"] for r in unscaled) == pytest.approx(
        sorted(r["amount"] for r in column))
    req = q(calc, f'RESULT REQUIREMENTS OF PROCESS "{me}"')["rows"]
    assert near(req[0]["amount"], 1.0)
    assert q(calc, "RESULT REQUIREMENTS TOP 5")["rows"]
    tot = q(calc, f'RESULT TOTALITY OF PROCESS "{me}"')["rows"]
    assert near(tot[0]["amount"], 1.0)
    assert q(calc, "RESULT TOTALITY TOP 5")["rows"]


def test_tree_adds_up(calc, category, flow):
    name, total = category
    r = q(calc, f'RESULT TREE CATEGORY "{name}" LEVELS 1 TOP 10')
    root = r["root"]
    assert root["process"] == calc["name"] and near(root["amount"], total)
    branches = sum(k["amount"] for k in root["children"])
    branches += root.get("other", {}).get("amount", 0.0)
    assert near(branches + (root["direct"] or 0.0), total)
    assert len(root["children"]) == 4
    r = q(calc, f'RESULT TREE FLOW "{flow["flow_id"]}" LEVELS 1')
    assert near(r["root"]["amount"], flow["amount"])


def test_sankey(calc, category):
    name, total = category
    r = q(calc, f'RESULT SANKEY CATEGORY "{name}" MAX NODES 10')
    assert 1 <= len(r["nodes"]) <= 10
    root = r["nodes"][r["root_index"]] if r["nodes"][0].get("index") is None \
        else next(n for n in r["nodes"] if n["index"] == r["root_index"])
    assert root["process"] == calc["name"] and near(root["amount"], total)
    assert r["edges"]


def test_queries_that_this_result_cannot_answer(calc):
    session = calc["live"].session
    r = session.run("RESULT COSTS")
    assert not r.ok and "without costs" in r.errors[0]["message"]
    r = session.run("RESULT NORMALISED")
    assert not r.ok and "normalisation and weighting set" in r.errors[0]["message"]
    r = session.run("RESULT IMPACTS BY GROUP")
    assert not r.ok and "no analysis groups" in r.errors[0]["message"]
    r = session.run('RESULT FLOWS OF PROCESS "olcaBASIC no such process"')
    assert not r.ok and "is in this result" in r.errors[0]["message"]


def test_costs(calc, live):
    """A second, named result with costs, beside the current one."""
    name, method = calc["name"], calc["method"]
    live.run(f'CALCULATE "{name}" USING "{method}" WITH COSTS AS costed')
    try:
        assert sorted(live.session.open_results) == ["", "costed"]
        total = live.run("RESULT COSTS IN costed")["rows"][0]["amount"]
        by = live.run("RESULT COSTS BY PROCESS IN costed")
        assert near(sum(r["amount"] for r in by["rows"]), total)
        me = live.run(f'RESULT COSTS OF PROCESS "{name}" IN costed')
        assert near(me["rows"][0]["amount"], total)
        tree = live.run("RESULT COSTS TREE LEVELS 1 IN costed")
        assert near(tree["root"]["amount"], total)
        per = live.run(f'RESULT COSTS INTENSITY OF PROCESS "{name}" IN costed')
        assert near(per["rows"][0]["amount"], total)
        live.run(f'RESULT COSTS OF PROCESS "{name}" DIRECT IN costed')
    finally:
        live.run("CLOSE RESULT costed")
    assert live.session.open_results == [""]


def test_amount(calc, live, category):
    name, total = category
    got = live.run(f'CALCULATE "{calc["name"]}" USING "{calc["method"]}" '
                   f'AMOUNT 2500 g AS more')
    try:
        amount = next(i["amount"] for i in got["impacts"]
                      if i["category"] == name)
        assert near(amount, 2.5 * total)
    finally:
        live.run("CLOSE RESULT more")


def test_the_older_commands_reuse_the_open_result(calc, live):
    """INVENTORY and TREE on the same system and method read the
    current result: no second calculation is opened."""
    before = len(live.engine.open_results())
    got = live.run(f'INVENTORY "{calc["name"]}" USING "{calc["method"]}" MAX 5')
    assert got["flow_count"] == 5
    assert len(live.engine.open_results()) == before


def test_closing_disposes_the_result_in_openlca(live, calc):
    """After CLOSE RESULT openLCA no longer knows the result."""
    live.run(f'CALCULATE "{calc["name"]}" USING "{calc["method"]}" AS gone')
    handle = live.session.runtime.open_results["gone"]["handle"]
    uid = live.engine._results()[handle].result.uid
    state, err = live.engine.client.rpc_call("result/state", {"@id": uid})
    assert not err and state.get("isReady")
    live.run("CLOSE RESULT gone")
    state, err = live.engine.client.rpc_call("result/state", {"@id": uid})
    assert err or not (state or {}).get("isReady")
    totals, err = live.engine.client.rpc_call("result/total-impacts",
                                              {"@id": uid})
    assert err or not totals
