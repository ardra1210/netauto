"""Shared enumerations (stdlib only, so every module can use them)."""
from enum import Enum


class Role(str, Enum):
    LEAF = "leaf"    # top-of-rack switch; servers plug into it
    SPINE = "spine"  # aggregation switch; every leaf connects to every spine


class PortMode(str, Enum):
    ACCESS = "access"  # carries one untagged VLAN (e.g. a server NIC)
    TRUNK = "trunk"    # carries several tagged VLANs
    ROUTED = "routed"  # layer-3 point-to-point link (leaf <-> spine uplink)


class Severity(str, Enum):
    ERROR = "error"      # blocks config generation
    WARNING = "warning"  # allowed, but someone should look
