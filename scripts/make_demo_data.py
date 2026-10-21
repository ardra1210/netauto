"""Generate demo inputs: a drifted 'running config' and synthetic interface metrics.

    python scripts/make_demo_data.py
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import renderer  # noqa: E402
from app.source_of_truth import YamlSourceOfTruth  # noqa: E402

OUT = ROOT / "data" / "demo"
OUT.mkdir(parents=True, exist_ok=True)

# 1) Running config = intended config + three realistic manual changes.
ctx = YamlSourceOfTruth(ROOT / "data" / "racks").get_rack("sjc01-r01")
intended = renderer.render_rack(ctx)["sjc01-r01-leaf1"]
running = (intended
           .replace("   switchport access vlan 200\n", "   switchport access vlan 100\n")  # wrong VLAN
           .replace("   description uplink-spine2\n   no switchport\n   mtu 9214\n",
                    "   description uplink-spine2\n   no switchport\n   mtu 1500\n")      # MTU reset
           .replace("ip routing\n", "ip routing\n!\ninterface Ethernet20\n   description temp-debug\n   no shutdown\n"))  # stray port
(OUT / "leaf1-running.cfg").write_text(running)

# 2) Interface metrics: normal noise, plus injected incidents.
random.seed(7)
samples = []
for dev in ("sjc01-r01-leaf1", "sjc01-r01-leaf2"):
    for iface in ("Ethernet49", "Ethernet50"):
        for t in range(60):
            util = 40 + random.gauss(0, 3)            # % utilization
            errors = max(0, round(random.gauss(2, 1)))  # input errors per minute
            if dev.endswith("leaf1") and iface == "Ethernet50" and t in (41, 42, 43):
                errors += 250                            # a dirty optic / bad cable
            if dev.endswith("leaf2") and iface == "Ethernet49" and t == 30:
                util = 2                                 # traffic suddenly drained
            ts = 1_760_000_000 + t * 60
            samples.append({"device": dev, "interface": iface, "metric": "utilization_pct",
                            "timestamp": ts, "value": round(util, 2)})
            samples.append({"device": dev, "interface": iface, "metric": "input_errors",
                            "timestamp": ts, "value": errors})
(OUT / "metrics.json").write_text(json.dumps({"samples": samples}))
print(f"wrote {OUT/'leaf1-running.cfg'} and {OUT/'metrics.json'} ({len(samples)} samples)")
