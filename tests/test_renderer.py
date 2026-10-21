from ipaddress import ip_interface

from app import ipam, renderer
from tests.helpers import good_rack


def test_every_device_gets_a_config():
    ctx = good_rack()
    assert set(renderer.render_rack(ctx)) == {d.name for d in ctx.devices}


def test_rendering_is_deterministic():
    """Idempotency: same input must always give byte-identical output."""
    assert renderer.render_rack(good_rack()) == renderer.render_rack(good_rack())


def test_yaml_order_does_not_change_addressing():
    a = good_rack()
    b = good_rack()
    b.devices.reverse()
    b.cables.reverse()
    assert renderer.render_rack(a) == renderer.render_rack(b)


def test_p2p_links_share_a_31_and_neighbors_point_at_each_other():
    ctx = good_rack()
    addr = ipam.allocate(ctx)
    for c in ctx.cables:
        a = addr[c.a_device].interface_ips[c.a_port]
        b = addr[c.b_device].interface_ips[c.b_port]
        assert a.network == b.network and a.network.prefixlen == 31 and a != b
        assert str(b.ip) in {n["ip"] for n in addr[c.a_device].bgp_neighbors}
        assert str(a.ip) in {n["ip"] for n in addr[c.b_device].bgp_neighbors}


def test_loopbacks_unique_and_inside_pool():
    ctx = good_rack()
    loops = [a.loopback for a in ipam.allocate(ctx).values()]
    assert len(set(loops)) == len(loops)
    assert all(lo.ip in ctx.loopback_pool and lo.network.prefixlen == 32 for lo in loops)


def test_leaf_config_contents():
    cfg = renderer.render_rack(good_rack())["sjc01-r01-leaf1"]
    assert "hostname sjc01-r01-leaf1" in cfg
    assert "router bgp 65101" in cfg
    assert cfg.count("remote-as 65000") == 2          # one session per spine
    assert "switchport trunk allowed vlan 100,200,300" in cfg
    assert "vlan 300" in cfg                            # only via the trunk


def test_disabled_port_is_shutdown_and_unused_vlans_omitted():
    cfg = renderer.render_rack(good_rack())["sjc01-r01-leaf2"]
    block = cfg.split("interface Ethernet3\n")[1].split("!")[0]
    assert "   shutdown" in block and "no shutdown" not in block
    assert "vlan 200" not in cfg                        # leaf2 doesn't use storage VLAN


def test_spine_has_no_vlans_and_peers_with_each_leaf():
    cfg = renderer.render_rack(good_rack())["sjc01-spine1"]
    assert "switchport" not in cfg.replace("no switchport", "")
    assert "remote-as 65101" in cfg and "remote-as 65102" in cfg


def test_all_rendered_ips_parse():
    for cfg in renderer.render_rack(good_rack()).values():
        for line in cfg.splitlines():
            if line.strip().startswith("ip address"):
                ip_interface(line.split()[-1])  # raises if malformed
