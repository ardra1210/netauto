"""Tiny IPAM (IP Address Management).

Hands out:
  * one /32 loopback per device (a stable "router ID" address)
  * one /31 per leaf-spine cable (RFC 3021: two usable addresses, no waste)

Allocation is DETERMINISTIC: same input -> same addresses, every time. That
makes config generation idempotent — re-running a build never renumbers a
live network, and re-rendered configs can be diffed meaningfully.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Interface


@dataclass
class DeviceAddressing:
    loopback: IPv4Interface
    interface_ips: dict[str, IPv4Interface] = field(default_factory=dict)
    bgp_neighbors: list[dict] = field(default_factory=list)


def allocate(ctx) -> dict[str, DeviceAddressing]:
    devices = {d.name: d for d in ctx.devices}

    # Sort by name so the order in the YAML file doesn't change addresses.
    loopback_hosts = ctx.loopback_pool.hosts()
    result: dict[str, DeviceAddressing] = {}
    for name in sorted(devices):
        result[name] = DeviceAddressing(loopback=IPv4Interface(f"{next(loopback_hosts)}/32"))

    # Sort cables by a stable key for the same reason.
    p2p_subnets = ctx.p2p_pool.subnets(new_prefix=31)
    for cable in sorted(ctx.cables, key=lambda c: (c.a_device, c.a_port, c.b_device, c.b_port)):
        subnet = next(p2p_subnets)
        a_ip, b_ip = (IPv4Interface(f"{ip}/31") for ip in subnet)  # a /31 has exactly 2 addresses
        result[cable.a_device].interface_ips[cable.a_port] = a_ip
        result[cable.b_device].interface_ips[cable.b_port] = b_ip
        result[cable.a_device].bgp_neighbors.append(
            {"ip": str(b_ip.ip), "asn": devices[cable.b_device].asn, "description": f"{cable.b_device}:{cable.b_port}"})
        result[cable.b_device].bgp_neighbors.append(
            {"ip": str(a_ip.ip), "asn": devices[cable.a_device].asn, "description": f"{cable.a_device}:{cable.a_port}"})
    return result
