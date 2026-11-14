"""The engine lives in olcaBASIC and is used through its public API."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import olca_schema as o

from fake_client import ELECTRICITY, STEEL

PACKAGE = Path(__file__).resolve().parents[1] / "olcabasic"


def test_engine_is_exported_and_keeps_its_old_name():
    import olcabasic
    from olcabasic.engine import Engine, LCAFunctions
    assert olcabasic.Engine is Engine and LCAFunctions is Engine


def test_importing_olcabasic_does_not_need_the_mcp():
    code = ("import sys, olcabasic, olcabasic.interpreter, olcabasic.bridge, "
            "olcabasic.engine; "
            "print('mcp' in sys.modules, 'b280_olca_mcp' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True).stdout.split()
    assert out == ["False", "False"]


def test_pyproject_depends_on_olca_ipc_only():
    text = (PACKAGE.parent / "pyproject.toml").read_text(encoding="utf-8")
    deps = re.search(r"\ndependencies = \[(.*?)\]", text, re.S).group(1)
    assert "olca-ipc>=2.4.0,<3" in deps and "b280" not in deps and "mcp" not in deps


def test_nothing_outside_the_engine_uses_its_private_names():
    """No module outside engine/ may reach an underscore name on the
    engine (written as .lca._x, .engine._x or bridge._x)."""
    pattern = re.compile(r"\b(?:lca|engine)\._[a-z]")
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        if "engine" in path.relative_to(PACKAGE).parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert offenders == []


def test_interpreter_does_not_reach_through_the_bridge():
    text = (PACKAGE / "interpreter.py").read_text(encoding="utf-8")
    assert "bridge.lca" not in text and "bridge.engine" not in text


def test_validators_are_public():
    from olcabasic.engine import validators as v
    assert v.validate_category("a/../b") and v.validate_category("a/b") is None
    assert v.validate_param_name("2x") and v.validate_param_name("x2") is None
    assert v.validate_formula("eval(1)") and v.validate_formula("a * 2") is None
    assert v.validate_uuid("nope") and v.validate_uuid(
        "00000000-0000-0000-0000-000000000000") is None


def test_ipc_reference_moved_with_the_engine():
    from olcabasic.engine.ipc_reference import IPC_PROTOCOL_REFERENCE
    assert "JSON-RPC" in IPC_PROTOCOL_REFERENCE


# ── public accessors ─────────────────────────────────────────

def test_get_descriptors_and_cache(engine, client):
    assert engine.cache_size() == 0
    assert len(engine.get_descriptors(o.Process)) == 10
    assert engine.cache_size() == 1
    client.calls.clear()
    engine.get_descriptors(o.Process)
    assert client.calls == []          # served from the cache
    engine.clear_caches()
    assert engine.cache_size() == 0


def test_find_process_system_method(engine):
    assert engine.find_process(STEEL).name == STEEL
    assert engine.find_process("test steel").name == STEEL       # unique part
    assert engine.find_process("test electricity") is None       # three match
    assert engine.find_method("EF v3.1").name == "EF v3.1"       # exact wins
    assert engine.find_system("nothing") is None


def test_database_family_property(engine):
    assert engine.database_family == "ecoinvent"


# ── resolution (moved from bridge.py) ────────────────────────

def test_resolve_process(engine, client):
    steel = client.by_name(o.Process, STEEL)[0]
    assert engine.resolve_process(STEEL) == steel.id
    assert engine.resolve_process(steel.id) == steel.id
    assert engine.resolve_process("no such") is None


def test_resolve_process_strict(engine, client):
    steel = client.by_name(o.Process, STEEL)[0]
    assert engine.resolve_process_strict(steel.id) == {"process_id": steel.id}
    assert engine.resolve_process_strict("test steel") == {"process_id": steel.id}
    amb = engine.resolve_process_strict(ELECTRICITY)
    assert amb["ambiguous"] == 3 and "locations: DE, GB, RoW" in amb["error"]
    assert "partial name" in engine.resolve_process_strict("market for test")["error"]
    assert "Process not found" in engine.resolve_process_strict("zzz")["error"]


def test_find_flow(engine):
    hit = engine.find_flow("test water")
    assert hit["flow_name"] == "test water" and hit["already_existed"]
    assert engine.find_flow("nothing like this") is None
    co2 = engine.find_flow("Carbon dioxide, fossil", "",
                           ["Elementary flows/emission to air"], strict=True)
    assert co2["ambiguous"] == 2 and co2["category"].endswith("unspecified")
    assert engine.find_flow("Carbon dioxide, fossil", "",
                            ["Elementary flows/emission to water"],
                            strict=True) is None


def test_find_process_qref_flow(engine):
    one = engine.find_process_qref_flow(STEEL)
    assert set(one) == {"flow_id", "flow_name", "process_id", "process_name",
                        "location", "unit"}
    assert one["unit"] == "kg" and one["location"] == "GLO"
    amb = engine.find_process_qref_flow(ELECTRICITY)
    assert amb["ambiguous"] == 3
    gb = engine.find_process_qref_flow(ELECTRICITY, "gb")
    assert gb["location"] == "GB" and "ambiguous" not in gb
    assert "Available: DE, GB, RoW" in engine.find_process_qref_flow(
        ELECTRICITY, "FR")["error"]
    assert engine.find_process_qref_flow("no such process") is None


def test_resolve_entity_strict(engine, client):
    steel = client.by_name(o.Process, STEEL)[0]
    assert engine.resolve_entity_strict("process", STEEL) == {
        "id": steel.id, "name": STEEL}
    assert engine.resolve_entity_strict("process", "zzz") == {"not_found": True}
    assert "3 processes are called" in engine.resolve_entity_strict(
        "process", ELECTRICITY)["error"]
    assert "Unknown entity type" in engine.resolve_entity_strict("method", "x")["error"]


def test_resolve_flow_id_finds_or_creates(engine, client):
    existing = client.by_name(o.Flow, "test water")[0]
    assert engine.resolve_flow_id("test water", "kg") == existing.id
    new_id = engine.resolve_flow_id("Brand new flow", "kg", "00: Test")
    assert client.store["Flow"][new_id].name == "Brand new flow"
    assert engine.resolve_flow_id("Bad unit flow", "furlong") is None


def test_folders(engine):
    assert engine.folder_exists("C:Test manufacturing")
    assert engine.folder_exists("D:Test supply/35:Test supply", "PROCESSES")
    assert not engine.folder_exists("C:Test")            # whole segments only
    root = engine.list_category_contents("", "PROCESSES")
    assert root["path"] == "(root)" and root["entity_count"] == 0
    assert "C:Test manufacturing" in root["subfolders"]
    inner = engine.list_category_contents("C:Test manufacturing", "PROCESSES")
    assert inner["entity_count"] == 3 and inner["subfolder_count"] == 0
    assert {e["type"] for e in inner["entities"]} == {"process"}


def test_get_flow_details_and_process_object(engine, client):
    water = client.by_name(o.Flow, "test water")[0]
    d = engine.get_flow_details(water.id)
    assert d["name"] == "test water" and d["type"] == "product"
    assert d["properties"] == [{"name": "Mass", "factor": 1.0,
                                "reference": True, "unit": "kg"}]
    assert "Flow not found" in engine.get_flow_details("nope")["error"]
    steel = client.by_name(o.Process, STEEL)[0]
    assert engine.get_process_object(steel.id).name == STEEL


def test_details_by_name_or_id(engine, client):
    steel = client.by_name(o.Process, STEEL)[0]
    assert engine.get_process_details_by_ref(STEEL)["id"] == steel.id
    assert engine.get_process_details_by_ref(steel.id)["id"] == steel.id


# ── the bridge is only an adapter ────────────────────────────

def test_bridge_hands_calls_to_the_engine(bridge, engine):
    assert bridge.engine is engine and bridge.lca is engine
    assert bridge.database_info() == engine.get_database_info()
    assert bridge.list_methods("IPCC") == engine.list_impact_methods("IPCC")
    assert bridge.resolve_process(STEEL) == engine.resolve_process(STEEL)


def test_bridge_refuses_when_not_connected():
    from olcabasic.bridge import LCABridge
    b = LCABridge()
    assert not b.connected
    with pytest.raises(RuntimeError) as e:
        b.database_info()
    assert "Not connected to openLCA" in str(e.value)


def test_csv_runners_go_through_the_bridge(run, interp, tmp_path):
    from test_interpreter_lca import WIDGET
    run(WIDGET)
    scen = tmp_path / "scen.csv"
    scen.write_text("Parameter,Low,High\nelec,1,5\n", encoding="utf-8")
    out = run(f'RUN SCENARIOS ON "Widget" USING "IPCC 2021"\n'
              f'  FROM CSV "{scen.as_posix()}"\nEND RUN')
    assert interp.runtime.last_results_type == "scenarios", out
    sens = tmp_path / "sens.csv"
    sens.write_text("Parameter\nelec\n", encoding="utf-8")
    run(f'SENSITIVITY ON "Widget" USING "IPCC 2021" BY 10\n'
        f'  FROM "{sens.as_posix()}"\nEND SENSITIVITY')
    assert interp.runtime.last_results_type == "sensitivity"
