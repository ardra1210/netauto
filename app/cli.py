"""Command-line interface — handy for CI and for demos without starting the server.

    python -m app.cli validate-all
    python -m app.cli render sjc01-r01 --out build/
    python -m app.cli drift sjc01-r01 sjc01-r01-leaf1 data/demo/leaf1-running.cfg
    python -m app.cli anomalies data/demo/metrics.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app import anomaly, drift, renderer, validator
from app.source_of_truth import InvalidRackData, YamlSourceOfTruth

DATA_DIR = Path(os.getenv("NETAUTO_DATA_DIR", Path(__file__).parent.parent / "data" / "racks"))


def cmd_validate_all(args) -> int:
    sot, failed = YamlSourceOfTruth(DATA_DIR), []
    for rack_id in sot.list_racks():
        try:
            issues = validator.validate(sot.get_rack(rack_id))
        except InvalidRackData as exc:
            print(f"✗ {rack_id}: schema error {exc.errors}")
            failed.append(rack_id)
            continue
        ok = not validator.has_errors(issues)
        print(f"{'✓' if ok else '✗'} {rack_id}: {len(issues)} issue(s)")
        for i in issues:
            print(f"    [{i.severity.value}] {i.code}: {i.message}")
        if not ok and rack_id not in args.allow:
            failed.append(rack_id)
    return 1 if failed else 0


def cmd_render(args) -> int:
    ctx = YamlSourceOfTruth(DATA_DIR).get_rack(args.rack_id)
    issues = validator.validate(ctx)
    if validator.has_errors(issues):
        print("refusing to render: rack has validation errors (run validate-all)", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, cfg in renderer.render_rack(ctx).items():
        (out / f"{name}.cfg").write_text(cfg)
        print(f"wrote {out / name}.cfg")
    return 0


def cmd_drift(args) -> int:
    ctx = YamlSourceOfTruth(DATA_DIR).get_rack(args.rack_id)
    intended = renderer.render_rack(ctx)[args.device]
    report = drift.detect_drift(args.device, intended, Path(args.running).read_text())
    if report.in_sync:
        print(f"{args.device}: in sync ✓")
        return 0
    print(report.unified_diff)
    print("Remediation commands:")
    print("\n".join(report.remediation))
    return 2


def cmd_anomalies(args) -> int:
    samples = json.loads(Path(args.metrics).read_text())["samples"]
    found = anomaly.detect_anomalies(samples, args.threshold)
    print(f"{len(found)} anomaly(ies) in {len(samples)} samples")
    for a in found:
        print(f"  t={a['timestamp']} {a['device']} {a['interface']} {a['metric']}="
              f"{a['value']} score={a['score']} ({a['direction']})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="netauto")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate-all")
    v.add_argument("--allow", nargs="*", default=[], help="racks allowed to fail (e.g. demo fixtures)")
    r = sub.add_parser("render")
    r.add_argument("rack_id")
    r.add_argument("--out", default="build")
    d = sub.add_parser("drift")
    d.add_argument("rack_id")
    d.add_argument("device")
    d.add_argument("running")
    a = sub.add_parser("anomalies")
    a.add_argument("metrics")
    a.add_argument("--threshold", type=float, default=4.0)
    args = p.parse_args(argv)
    return {"validate-all": cmd_validate_all, "render": cmd_render,
            "drift": cmd_drift, "anomalies": cmd_anomalies}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
