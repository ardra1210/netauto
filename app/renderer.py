"""Day-0 configuration generation: YAML context -> IPAM -> Jinja2 -> config text."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.enums import PortMode
from app.ipam import allocate

TEMPLATE_DIR = Path(__file__).parent / "templates"

# StrictUndefined: a typo in a template variable raises an error instead of
# silently rendering an empty string into a switch config.
_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def build_device_context(ctx, device, addressing) -> dict:
    vlan_names = {v.id: v.name for v in ctx.vlans}
    used_vlans: set[int] = set()
    interfaces = []
    for iface in sorted(device.interfaces, key=lambda i: int(i.name.removeprefix("Ethernet"))):
        entry = {
            "name": iface.name,
            "description": iface.description,
            "mode": iface.mode.value,
            "enabled": iface.enabled,
            "vlan": iface.vlan,
            "allowed_vlans": ",".join(str(v) for v in sorted(iface.allowed_vlans)),
            "ip": str(addressing.interface_ips[iface.name]) if iface.name in addressing.interface_ips else None,
        }
        if iface.mode == PortMode.ACCESS:
            used_vlans.add(iface.vlan)
        elif iface.mode == PortMode.TRUNK:
            used_vlans.update(iface.allowed_vlans)
        interfaces.append(entry)

    return {
        "hostname": device.name,
        "role": device.role.value,
        "site": ctx.site,
        "rack_id": ctx.rack_id,
        "mgmt_ip": str(device.mgmt_ip),
        "asn": device.asn,
        "loopback": str(addressing.loopback),
        "router_id": str(addressing.loopback.ip),
        "vlans": [{"id": v, "name": vlan_names[v]} for v in sorted(used_vlans)],
        "interfaces": interfaces,
        "bgp_neighbors": sorted(addressing.bgp_neighbors, key=lambda n: n["ip"]),
    }


def render_device(ctx, device, addressing) -> str:
    template = _env.get_template("switch.j2")
    return template.render(**build_device_context(ctx, device, addressing))


def render_rack(ctx) -> dict[str, str]:
    """Render every device in the rack. Caller must validate first."""
    addressing = allocate(ctx)
    return {d.name: render_device(ctx, d, addressing[d.name]) for d in ctx.devices}
