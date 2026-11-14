"""The command line: python -m olcabasic run file.baslca."""

import subprocess
import sys


def run(*args):
    return subprocess.run([sys.executable, "-m", "olcabasic", "--no-connect",
                           *args], capture_output=True, text=True,
                          timeout=60)


def test_a_program_file_runs(tmp_path):
    f = tmp_path / "p.baslca"
    f.write_text("PRINT 6 * 7\n", encoding="utf-8")
    r = run("run", str(f))
    assert r.returncode == 0 and "42" in r.stdout


def test_a_missing_program_file(tmp_path):
    r = run("run", str(tmp_path / "nope.baslca"))
    assert r.returncode == 1 and "Program file not found" in r.stdout
