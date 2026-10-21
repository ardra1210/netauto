from app import drift, renderer
from tests.helpers import good_rack

INTENDED = renderer.render_rack(good_rack())["sjc01-r01-leaf1"]


def test_identical_configs_are_in_sync():
    report = drift.detect_drift("leaf1", INTENDED, INTENDED)
    assert report.in_sync and report.remediation == [] and report.unified_diff == ""


def test_comments_and_blank_lines_are_ignored():
    noisy = INTENDED.replace("!\n", "!\n\n! touched by ops\n")
    assert drift.detect_drift("leaf1", INTENDED, noisy).in_sync


def test_changed_setting_is_reported_under_its_interface():
    running = INTENDED.replace("switchport access vlan 200", "switchport access vlan 100")
    report = drift.detect_drift("leaf1", INTENDED, running)
    assert not report.in_sync
    assert report.changed_sections == {
        "interface Ethernet3": {"missing": ["switchport access vlan 200"],
                                "unexpected": ["switchport access vlan 100"]}}
    assert report.remediation == ["interface Ethernet3",
                                  "   no switchport access vlan 100",
                                  "   switchport access vlan 200"]


def test_extra_and_missing_sections():
    running = INTENDED.replace("interface Ethernet10\n", "interface Ethernet11\n")
    report = drift.detect_drift("leaf1", INTENDED, running)
    assert report.missing_sections == ["interface Ethernet10"]
    assert report.unexpected_sections == ["interface Ethernet11"]
    assert "no interface Ethernet11" in report.remediation


def test_shutdown_flip_negates_correctly():
    running = INTENDED.replace(
        "   description server-01-nic0\n   switchport mode access\n   switchport access vlan 100\n   no shutdown",
        "   description server-01-nic0\n   switchport mode access\n   switchport access vlan 100\n   shutdown")
    report = drift.detect_drift("leaf1", INTENDED, running)
    assert report.remediation == ["interface Ethernet1", "   no shutdown"]  # emitted once, not twice


def test_parse_config_groups_children():
    parsed = drift.parse_config("hostname x\n!\ninterface Ethernet1\n   description a\n   no shutdown\n")
    assert parsed == {"hostname x": [], "interface Ethernet1": ["description a", "no shutdown"]}
