"""test_features.baslca must keep parsing to the v0.3.0 baseline."""

from collections import Counter
from pathlib import Path

from olcabasic.parser import parse

ROOT = Path(__file__).resolve().parents[1]

# Recorded from olcaBASIC v0.3.0 (commit 322b63e) before the rebuild.
BASELINE = {
    "BackStmt": 1, "CalculateStmt": 3, "CatStmt": 8, "ConfirmDeleteStmt": 1,
    "DeleteStmt": 12, "DirStmt": 4, "EditFlowStmt": 1, "EditProcessStmt": 2,
    "FindStmt": 3, "ForEachStmt": 1, "ForStmt": 1, "LetStmt": 3, "LinkStmt": 1,
    "MoveStmt": 1, "NavigateStmt": 2, "PrintExprStmt": 20, "PrintStmt": 4,
    "ProcessStmt": 3, "PwdStmt": 5, "RunScenariosStmt": 1, "SaveResultsStmt": 2,
    "ScenarioStmt": 3, "SensitivityStmt": 1, "SetFolderStmt": 3, "ShowStmt": 6,
    "SystemStmt": 2, "TreeStmt": 2, "UpStmt": 1, "UpdateParamStmt": 2,
}


def _statements():
    source = (ROOT / "test_features.baslca").read_text(encoding="utf-8")
    return parse(source)


def test_statement_count():
    assert len(_statements()) == 99


def test_statement_types():
    counts = Counter(type(s).__name__ for s in _statements())
    assert dict(counts) == BASELINE


def test_every_statement_has_a_line():
    assert all(s.line > 0 for s in _statements())
