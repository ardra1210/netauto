"""Day-2 configuration drift detection and remediation.

"Drift" = the config actually running on a switch no longer matches the
intended config generated from the source of truth (someone hot-fixed a
port by hand, a firmware upgrade reset a setting, etc.).

Switch configs are hierarchical: a parent line ("interface Ethernet1")
owns indented child lines. A flat line diff would say "a 'no shutdown'
line is missing" without saying WHICH interface — useless for fixing it.
So we parse into {parent: [children]} and compare section by section.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

IGNORED_PREFIXES = ("!", "end")


def parse_config(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith(IGNORED_PREFIXES):
            continue
        if line.startswith((" ", "\t")) and current is not None:
            sections[current].append(stripped)
        else:
            current = stripped
            sections.setdefault(current, [])
    return sections


@dataclass
class DriftReport:
    device: str
    in_sync: bool
    missing_sections: list[str] = field(default_factory=list)
    unexpected_sections: list[str] = field(default_factory=list)
    changed_sections: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    remediation: list[str] = field(default_factory=list)
    unified_diff: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def detect_drift(device: str, intended: str, running: str) -> DriftReport:
    want, have = parse_config(intended), parse_config(running)
    report = DriftReport(device=device, in_sync=True)
    fix: list[str] = []

    for parent, children in want.items():
        if parent not in have:
            report.missing_sections.append(parent)
            fix += [parent] + [f"   {c}" for c in children]
            continue
        missing = [c for c in children if c not in have[parent]]
        extra = [c for c in have[parent] if c not in children]
        if missing or extra:
            report.changed_sections[parent] = {"missing": missing, "unexpected": extra}
            cmds = [_negate(c) for c in extra]
            cmds += [c for c in missing if c not in cmds]  # 'shutdown' -> 'no shutdown' only once
            fix.append(parent)
            fix += [f"   {c}" for c in cmds]

    for parent in have:
        if parent not in want:
            report.unexpected_sections.append(parent)
            fix.append(_negate(parent))

    report.in_sync = not (report.missing_sections or report.unexpected_sections or report.changed_sections)
    report.remediation = fix
    report.unified_diff = "".join(difflib.unified_diff(
        _normalized(running), _normalized(intended), fromfile=f"{device}:running", tofile=f"{device}:intended"))
    return report


def _negate(line: str) -> str:
    """'shutdown' -> 'no shutdown' and 'no shutdown' -> 'shutdown'."""
    return line[3:] if line.startswith("no ") else f"no {line}"


def _normalized(text: str) -> list[str]:
    return [line.rstrip() + "\n" for line in text.splitlines()
        if line.strip() and not line.strip().startswith(IGNORED_PREFIXES)]
