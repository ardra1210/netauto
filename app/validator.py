"""Layer 2 of validation: cross-object (semantic) rules.

Pydantic already guarantees each object is well-formed. These rules catch
mistakes that only show up when you look at the whole rack together, which
is exactly the kind of bad data that breaks a real network build.

Every rule returns Issue objects instead of raising, so the API can report
ALL problems at once rather than failing on the first one.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from app.enums import PortMode, Role, Severity


@dataclass(frozen=True)
class Issue:
    severity: Severity
    code: str
    message: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


def _dupes(values) -> list:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def check_unique_names(ctx) -> list[Issue]:
    issues = [Issue(Severity.ERROR, "DUPLICATE_DEVICE", f"device '{n}' defined more than once")
              for n in _dupes(d.name for d in ctx.devices)]
    for dev in ctx.devices:
        for n in _dupes(i.name for i in dev.interfaces):
            issues.append(Issue(Severity.ERROR, "DUPLICATE_INTERFACE", f"{dev.name}: '{n}' defined twice"))
    issues += [Issue(Severity.ERROR, "DUPLICATE_VLAN", f"VLAN {v} defined more than once")
               for v in _dupes(v.id for v in ctx.vlans)]
    return issues


def check_vlan_references(ctx) -> list[Issue]:
    known = {v.id for v in ctx.vlans}
    issues = []
    for dev in ctx.devices:
        for iface in dev.interfaces:
            used = ([iface.vlan] if iface.mode == PortMode.ACCESS else
                    iface.allowed_vlans if iface.mode == PortMode.TRUNK else [])
            for vid in used:
                if vid not in known:
                    issues.append(Issue(Severity.ERROR, "UNKNOWN_VLAN",
                                        f"{dev.name} {iface.name}: VLAN {vid} is not defined for this rack"))
    return issues


def check_cabling(ctx) -> list[Issue]:
    issues: list[Issue] = []
    devices = {d.name: d for d in ctx.devices}
    seen_ports: Counter = Counter()

    for c in ctx.cables:
        label = f"{c.a_device}:{c.a_port} <-> {c.b_device}:{c.b_port}"
        ends = [(c.a_device, c.a_port), (c.b_device, c.b_port)]
        broken = False
        for dev_name, port in ends:
            seen_ports[(dev_name, port)] += 1
            dev = devices.get(dev_name)
            if dev is None:
                issues.append(Issue(Severity.ERROR, "CABLE_UNKNOWN_DEVICE", f"{label}: no device '{dev_name}'"))
                broken = True
                continue
            iface = next((i for i in dev.interfaces if i.name == port), None)
            if iface is None:
                issues.append(Issue(Severity.ERROR, "CABLE_UNKNOWN_PORT", f"{label}: {dev_name} has no port {port}"))
                broken = True
            elif iface.mode != PortMode.ROUTED:
                issues.append(Issue(Severity.ERROR, "CABLE_PORT_NOT_ROUTED",
                                    f"{label}: {dev_name} {port} must be 'routed' for a fabric link"))
        if broken:
            continue
        roles = {devices[c.a_device].role, devices[c.b_device].role}
        if roles != {Role.LEAF, Role.SPINE}:
            issues.append(Issue(Severity.ERROR, "INVALID_TOPOLOGY",
                                f"{label}: fabric links must connect a leaf to a spine"))

    for (dev_name, port), n in seen_ports.items():
        if n > 1:
            issues.append(Issue(Severity.ERROR, "PORT_DOUBLE_CABLED", f"{dev_name} {port} appears in {n} cables"))

    # Warn about routed ports that nothing is plugged into.
    for dev in ctx.devices:
        for iface in dev.interfaces:
            if iface.mode == PortMode.ROUTED and (dev.name, iface.name) not in seen_ports:
                issues.append(Issue(Severity.WARNING, "ROUTED_PORT_UNCABLED",
                                    f"{dev.name} {iface.name} is routed but has no cable"))
    return issues


def check_bgp_asns(ctx) -> list[Issue]:
    """eBGP leaf-spine design: each leaf gets its own ASN, spines share one."""
    issues = []
    leaf_asns = [d.asn for d in ctx.devices if d.role == Role.LEAF]
    for asn in _dupes(leaf_asns):
        issues.append(Issue(Severity.ERROR, "DUPLICATE_LEAF_ASN", f"ASN {asn} is used by more than one leaf"))
    spine_asns = {d.asn for d in ctx.devices if d.role == Role.SPINE}
    if len(spine_asns) > 1:
        issues.append(Issue(Severity.WARNING, "SPINE_ASN_MISMATCH", f"spines use different ASNs: {sorted(spine_asns)}"))
    overlap = spine_asns & set(leaf_asns)
    if overlap:
        issues.append(Issue(Severity.ERROR, "LEAF_SPINE_ASN_CLASH", f"ASN(s) {sorted(overlap)} used by leaf and spine"))
    return issues


def check_ip_pools(ctx) -> list[Issue]:
    issues = []
    if ctx.loopback_pool.overlaps(ctx.p2p_pool):
        issues.append(Issue(Severity.ERROR, "POOL_OVERLAP", "loopback_pool and p2p_pool overlap"))
    if ctx.loopback_pool.num_addresses < len(ctx.devices):
        issues.append(Issue(Severity.ERROR, "LOOPBACK_POOL_EXHAUSTED", "not enough loopback addresses"))
    if ctx.p2p_pool.num_addresses < 2 * len(ctx.cables):
        issues.append(Issue(Severity.ERROR, "P2P_POOL_EXHAUSTED", "not enough /31 subnets for all cables"))
    mgmt = [str(d.mgmt_ip.ip) for d in ctx.devices]
    for ip in _dupes(mgmt):
        issues.append(Issue(Severity.ERROR, "DUPLICATE_MGMT_IP", f"management IP {ip} used twice"))
    return issues


RULES = [check_unique_names, check_vlan_references, check_cabling, check_bgp_asns, check_ip_pools]


def validate(ctx) -> list[Issue]:
    issues: list[Issue] = []
    for rule in RULES:
        issues.extend(rule(ctx))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == Severity.ERROR for i in issues)
