"""Source of Truth (SSOT) access layer.

The rest of the app only talks to the `SourceOfTruth` interface, never to
files directly. Today it's backed by YAML files; in production you'd add a
`NetBoxSourceOfTruth` (using the NetBox REST API / pynetbox) without
touching the API, validator or renderer. That's the same idea as NCS/Axon
consuming rack topology from SSOT/Hivemind.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import yaml
from pydantic import ValidationError

from app.models import RackContext


class RackNotFound(Exception):
    pass


class InvalidRackData(Exception):
    def __init__(self, rack_id: str, errors: list):
        super().__init__(f"rack {rack_id} failed schema validation")
        self.rack_id, self.errors = rack_id, errors


class SourceOfTruth(Protocol):
    def list_racks(self) -> list[str]: ...
    def get_rack(self, rack_id: str) -> RackContext: ...


class YamlSourceOfTruth:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def list_racks(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.yaml"))

    def get_rack(self, rack_id: str) -> RackContext:
        path = self.directory / f"{rack_id}.yaml"
        # Guard against path traversal ("../../etc/passwd") from the URL.
        if not path.resolve().is_relative_to(self.directory.resolve()) or not path.is_file():
            raise RackNotFound(rack_id)
        data = yaml.safe_load(path.read_text())  # safe_load: never execute YAML tags
        try:
            return RackContext.model_validate(data)
        except ValidationError as exc:
            raise InvalidRackData(rack_id, exc.errors(include_url=False)) from exc
