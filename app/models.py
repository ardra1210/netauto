"""Pydantic models for the rack context (the YAML input).

Layer 1 of validation: *schema* checks — types, ranges, formats, and rules
that only need one object at a time. Cross-object rules (e.g. "this cable
points at a port that exists") live in validator.py.
"""
from __future__ import annotations

from ipaddress import IPv4Interface, IPv4Network

from pydantic import BaseModel, Field, model_validator

from app.enums import PortMode, Role


class Vlan(BaseModel):
    id: int = Field(ge=2, le=4094, description="VLAN 1 is reserved; 4095 is invalid")
    name: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")


class Interface(BaseModel):
    name: str = Field(pattern=r"^Ethernet\d+$")
    description: str = ""
    mode: PortMode
    vlan: int | None = None
    allowed_vlans: list[int] = Field(default_factory=list)
    enabled: bool = True

    @model_validator(mode="after")
    def mode_fields_consistent(self) -> "Interface":
        if self.mode == PortMode.ACCESS and self.vlan is None:
            raise ValueError(f"{self.name}: access port needs 'vlan'")
        if self.mode == PortMode.TRUNK and not self.allowed_vlans:
            raise ValueError(f"{self.name}: trunk port needs 'allowed_vlans'")
        if self.mode == PortMode.ROUTED and (self.vlan or self.allowed_vlans):
            raise ValueError(f"{self.name}: routed port cannot carry VLANs")
        return self


class Device(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    role: Role
    model: str = "generic-switch"
    asn: int = Field(ge=64512, le=65534, description="private 2-byte BGP ASN range")
    mgmt_ip: IPv4Interface
    interfaces: list[Interface]


class Cable(BaseModel):
    a_device: str
    a_port: str
    b_device: str
    b_port: str


class RackContext(BaseModel):
    """Everything needed to build a rack: the 'source of truth' for one rack."""

    rack_id: str = Field(pattern=r"^[a-z0-9-]+$")
    site: str
    loopback_pool: IPv4Network
    p2p_pool: IPv4Network
    vlans: list[Vlan]
    devices: list[Device]
    cables: list[Cable] = Field(default_factory=list)

    def device(self, name: str) -> Device | None:
        return next((d for d in self.devices if d.name == name), None)
