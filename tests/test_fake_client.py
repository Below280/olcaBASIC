"""The fake client itself: enough checks to trust it as a test double."""

import pytest
import olca_schema as o

from fake_client import ELECTRICITY, FakeClient, eval_formula, seed_ecoinvent_like


def test_seed_is_deterministic():
    a, b = seed_ecoinvent_like(), seed_ecoinvent_like()
    assert sorted(a.store["Process"]) == sorted(b.store["Process"])


def test_same_name_processes_differ_by_location_only(client):
    refs = [r for r in client.get_descriptors(o.Process) if r.name == ELECTRICITY]
    assert sorted(r.location for r in refs) == ["DE", "GB", "RoW"]
    assert len({r.category for r in refs}) == 1


def test_get_returns_a_copy(client):
    ref = client.get_descriptors(o.Flow)[0]
    a = client.get(o.Flow, ref.id)
    a.name = "changed"
    assert client.get(o.Flow, ref.id).name != "changed"


def test_get_missing_is_none(client):
    assert client.get(o.Process, "nope") is None


def test_put_and_delete(empty_client):
    ref = empty_client.put(o.Actor(id="a1", name="Someone"))
    assert ref.id == "a1" and ref.name == "Someone"
    empty_client.delete(empty_client.get(o.Actor, "a1"))
    assert empty_client.get(o.Actor, "a1") is None


def test_location_descriptors_carry_no_code(client):
    ref = client.get_descriptors(o.Location)[0]
    assert not hasattr(ref, "code")


def test_formulas():
    values = {"a": 2.0, "b": 3.0}
    assert eval_formula("a * b + 2^2", values.get) == 10.0
    assert eval_formula("max(a, b)", values.get) == 3.0
    with pytest.raises(Exception):
        eval_formula("a * missing", values.get)


def test_calls_are_recorded_and_failures_can_be_injected(client):
    client.get_descriptors(o.Flow)
    assert client.calls[-1] == ("get_descriptors", "Flow")
    client.fail_next["put"] = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        client.put(o.Actor(name="x"))
    client.put(o.Actor(name="x"))


def test_disposed_result_cannot_be_read(client, engine):
    from olcabasic.interpreter import Interpreter  # noqa: F401  (import check)
    system_ref = None
    proc = client.by_name(o.Process, ELECTRICITY)[0]
    system_ref = client.create_product_system(o.Ref(id=proc.id))
    method = client.get_descriptors(o.ImpactMethod)[0]
    result = client.calculate(o.CalculationSetup(target=system_ref, impact_method=method))
    assert result.get_total_impacts()
    result.dispose()
    with pytest.raises(RuntimeError):
        result.get_total_impacts()
