# netauto — a mini Network Configuration Service

A small back-end service that automates the lifecycle of data-center switch
configuration, modeled on how cloud network teams run their fabric:

| Stage | What it does | Where |
|---|---|---|
| **Source of truth** | Rack topology (devices, ports, VLANs, cables) as YAML, behind a swappable interface (NetBox-ready) | `app/source_of_truth.py`, `data/racks/` |
| **Validation** | 2 layers: Pydantic schema checks + 17 cross-object checks (unknown VLANs, bad cabling, duplicate ASNs, IP pool overlap…) — reports *all* issues at once | `app/models.py`, `app/validator.py` |
| **Day-0 provisioning** | Deterministic IPAM (/32 loopbacks, /31 point-to-point links) → Jinja2 → full switch config incl. eBGP underlay. Plain-text endpoint for Zero Touch Provisioning | `app/ipam.py`, `app/renderer.py`, `app/templates/switch.j2` |
| **Day-2 drift** | Compares running vs intended config *per section* and generates remediation commands | `app/drift.py` |
| **Monitoring** | Robust rolling z-score (median/MAD) flags error spikes and traffic drops on interface metrics | `app/anomaly.py` |
| **API** | FastAPI REST API with OpenAPI docs, health/readiness probes, Prometheus metrics | `app/main.py` |
| **Delivery** | 41 tests (unit + API integration), multi-stage non-root Docker image, Kubernetes manifests, GitHub Actions CI | `tests/`, `Dockerfile`, `k8s/`, `.github/` |

```
           ┌──────────── netauto (FastAPI) ────────────┐
 YAML /    │                                            │
 NetBox ──►│ SourceOfTruth → Validator ─┬─► IPAM → Jinja2 ──► Day-0 configs / ZTP
           │                            │                  │
 running ─►│                            └─► Drift engine ────► remediation commands
 config    │                                            │
 metrics ─►│ Anomaly detector (median/MAD) ────────────────► alerts
           └───────────────── /healthz /readyz /metrics ┘
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q                                              # all tests should pass
make demo                                              # or run the 5 commands in the Makefile
uvicorn app.main:app --reload                          # then open http://localhost:8000/docs
```

Docker: `docker build -t netauto . && docker run -p 8000:8000 netauto`

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/racks` | list racks in the source of truth |
| GET | `/api/v1/racks/{rack_id}` | rack context as JSON |
| POST | `/api/v1/racks/{rack_id}/validate` | run all validation rules |
| POST | `/api/v1/day0/racks/{rack_id}/render` | generate every switch config (422 if data is invalid) |
| GET | `/api/v1/day0/racks/{rack_id}/devices/{device}/config` | plain-text config a ZTP script downloads |
| POST | `/api/v1/day2/drift` | `{rack_id, device, running_config}` → drift report + fix commands |
| POST | `/api/v1/monitoring/anomalies` | metric samples → anomalies |
| GET | `/healthz`, `/readyz`, `/metrics` | liveness, readiness, Prometheus metrics |

## Design decisions

* **Validate before you generate.** A bad config pushed to a switch can take down a rack. Rendering is blocked (HTTP 422) unless validation passes; warnings are returned but don't block.
* **Deterministic & idempotent.** IPs are allocated from sorted input, so re-running never renumbers a live network, and the same input always produces byte-identical configs (tested).
* **`StrictUndefined` in Jinja2.** A typo in a template fails loudly instead of rendering a blank line into production config.
* **Hierarchical drift diff.** Switch config is parent/child; diffing per section tells you *which interface* drifted and produces commands to fix it.
* **Robust statistics for monitoring.** Median/MAD instead of mean/std so one outage doesn't mask the next; a noise floor (`min_scale`) stops integer error counters from producing false alarms (found and fixed via a regression test).
* **Dependency injection.** The API depends on a `SourceOfTruth` interface; tests swap it, and a NetBox implementation could replace YAML without touching anything else.
* **Secure by default.** `yaml.safe_load`, path-traversal guard, non-root container with read-only filesystem and dropped Linux capabilities.

## What I'd add next
NetBox client via `pynetbox`; push configs to devices (Netmiko/NAPALM) with dry-run + automatic rollback; IPv6 underlay; persistence (PostgreSQL/CockroachDB) for drift history; Grafana dashboards / Zabbix alerts fed from `/metrics`; auth on write endpoints.
