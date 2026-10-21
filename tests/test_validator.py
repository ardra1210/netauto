from pydantic import ValidationError

from app import validator
from app.models import Interface, RackContext
from tests.helpers import broken_rack, good_rack


def codes(ctx):
    return {i.code for i in validator.validate(ctx)}


def test_good_rack_has_no_issues():
    assert validator.validate(good_rack()) == []


def test_broken_rack_reports_every_problem_at_once():
    found = codes(broken_rack())
    assert {"UNKNOWN_VLAN", "DUPLICATE_LEAF_ASN", "CABLE_UNKNOWN_PORT",
            "INVALID_TOPOLOGY", "PORT_DOUBLE_CABLED"} <= found
    assert validator.has_errors(validator.validate(broken_rack()))


def test_uncabled_routed_port_is_only_a_warning():
    ctx = good_rack()
    ctx.cables.pop()  # unplug one cable
    issues = validator.validate(ctx)
    assert [i.code for i in issues] == ["ROUTED_PORT_UNCABLED", "ROUTED_PORT_UNCABLED"]
    assert not validator.has_errors(issues)


def test_overlapping_ip_pools_detected():
    data = good_rack().model_dump(mode="json")
    data["p2p_pool"] = "10.255.0.128/25"  # inside loopback_pool 10.255.0.0/24
    assert "POOL_OVERLAP" in codes(RackContext.model_validate(data))


def test_p2p_pool_too_small():
    data = good_rack().model_dump(mode="json")
    data["p2p_pool"] = "10.254.0.0/30"  # room for 2 cables, rack has 4
    assert "P2P_POOL_EXHAUSTED" in codes(RackContext.model_validate(data))


def test_schema_rejects_access_port_without_vlan():
    try:
        Interface(name="Ethernet1", mode="access")
    except ValidationError as exc:
        assert "access port needs 'vlan'" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_schema_rejects_out_of_range_vlan():
    data = good_rack().model_dump(mode="json")
    data["vlans"].append({"id": 4095, "name": "bad"})
    try:
        RackContext.model_validate(data)
    except ValidationError:
        return
    raise AssertionError("VLAN 4095 should be rejected")
