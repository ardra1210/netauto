"""Tests for the command-line interface (also what CI runs)."""
from pathlib import Path

from app import cli, drift, renderer
from tests.helpers import good_rack

GOOD = "sjc01-r01"


def test_validate_all_fails_on_broken_rack_unless_allowed():
    assert cli.main(["validate-all"]) == 1
    assert cli.main(["validate-all", "--allow", "sjc01-r02-broken"]) == 0


def test_render_writes_one_file_per_device(tmp_path: Path):
    assert cli.main(["render", GOOD, "--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.glob("*.cfg")) == [
        "sjc01-r01-leaf1.cfg", "sjc01-r01-leaf2.cfg", "sjc01-spine1.cfg", "sjc01-spine2.cfg"]


def test_render_refuses_broken_rack(tmp_path: Path):
    assert cli.main(["render", "sjc01-r02-broken", "--out", str(tmp_path)]) == 1


def test_drift_exit_codes(tmp_path: Path):
    intended = renderer.render_rack(good_rack())["sjc01-r01-leaf1"]
    same, changed = tmp_path / "same.cfg", tmp_path / "changed.cfg"
    same.write_text(intended)
    changed.write_text(intended.replace("mtu 9214", "mtu 1500"))
    assert cli.main(["drift", GOOD, "sjc01-r01-leaf1", str(same)]) == 0
    assert cli.main(["drift", GOOD, "sjc01-r01-leaf1", str(changed)]) == 2
    assert not drift.detect_drift("x", intended, changed.read_text()).in_sync


def test_anomalies_command(tmp_path: Path):
    f = tmp_path / "m.json"
    f.write_text('{"samples": [' + ",".join(
        f'{{"device":"d","interface":"e","metric":"m","timestamp":{t},"value":{v}}}'
        for t, v in enumerate([1, 2, 1, 2, 1, 2, 90])) + "]}")
    assert cli.main(["anomalies", str(f)]) == 0