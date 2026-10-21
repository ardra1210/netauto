"""netauto REST API (FastAPI).

Run:  uvicorn app.main:app --reload     then open http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import os
import time
from collections import Counter
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app import anomaly, drift, renderer, validator
from app.source_of_truth import InvalidRackData, RackNotFound, SourceOfTruth, YamlSourceOfTruth

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}')
log = logging.getLogger("netauto")

DATA_DIR = Path(os.getenv("NETAUTO_DATA_DIR", Path(__file__).parent.parent / "data" / "racks"))

app = FastAPI(
    title="netauto",
    version="1.0.0",
    description="Mini network configuration service: validate rack data, generate Day-0 switch "
                "configs, detect Day-2 drift, and flag anomalous interface metrics.",
)

# --- simple in-process metrics (exposed in Prometheus text format) ---------
REQUESTS: Counter = Counter()
LATENCY_SUM: Counter = Counter()


@app.middleware("http")
async def record_metrics(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    key = (request.method, getattr(route, "path", "unmatched"), response.status_code)
    REQUESTS[key] += 1
    LATENCY_SUM[key[:2]] += time.perf_counter() - start
    return response


# --- dependency injection: tests swap this for a fake source of truth -------
def get_sot() -> SourceOfTruth:
    return YamlSourceOfTruth(DATA_DIR)


def load_rack(rack_id: str, sot: SourceOfTruth):
    try:
        return sot.get_rack(rack_id)
    except RackNotFound:
        raise HTTPException(404, f"rack '{rack_id}' not found")
    except InvalidRackData as exc:
        raise HTTPException(422, {"message": str(exc), "errors": exc.errors})


# --- request bodies ---------------------------------------------------------
class DriftRequest(BaseModel):
    rack_id: str
    device: str
    running_config: str = Field(min_length=1)


class MetricSample(BaseModel):
    device: str
    interface: str
    metric: str
    timestamp: int
    value: float


class AnomalyRequest(BaseModel):
    samples: list[MetricSample]
    threshold: float = Field(4.0, gt=0, description="robust z-score that counts as an anomaly")
    window: int = Field(20, ge=5, le=500, description="how many previous points form the baseline")
    min_scale: float = Field(1.0, gt=0, description="noise floor, in the metric's own units")


# --- health -----------------------------------------------------------------
@app.get("/healthz", tags=["ops"])
def healthz():
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
def readyz():
    """Readiness: we can reach our source of truth."""
    if not DATA_DIR.is_dir():
        raise HTTPException(503, "source of truth unavailable")
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse, tags=["ops"])
def metrics():
    lines = ["# TYPE netauto_requests_total counter"]
    for (method, path, status), n in sorted(REQUESTS.items()):
        lines.append(f'netauto_requests_total{{method="{method}",path="{path}",status="{status}"}} {n}')
    lines.append("# TYPE netauto_request_seconds_sum counter")
    for (method, path), s in sorted(LATENCY_SUM.items()):
        lines.append(f'netauto_request_seconds_sum{{method="{method}",path="{path}"}} {s:.6f}')
    return "\n".join(lines) + "\n"


# --- source of truth --------------------------------------------------------
@app.get("/api/v1/racks", tags=["source of truth"])
def list_racks(sot: SourceOfTruth = Depends(get_sot)):
    return {"racks": sot.list_racks()}


@app.get("/api/v1/racks/{rack_id}", tags=["source of truth"])
def get_rack(rack_id: str, sot: SourceOfTruth = Depends(get_sot)):
    return load_rack(rack_id, sot).model_dump(mode="json")


@app.post("/api/v1/racks/{rack_id}/validate", tags=["source of truth"])
def validate_rack(rack_id: str, sot: SourceOfTruth = Depends(get_sot)):
    ctx = load_rack(rack_id, sot)
    issues = validator.validate(ctx)
    return {"rack_id": rack_id, "valid": not validator.has_errors(issues),
            "issues": [i.to_dict() for i in issues]}


# --- Day-0 ------------------------------------------------------------------
@app.post("/api/v1/day0/racks/{rack_id}/render", tags=["day-0"])
def render_rack(rack_id: str, sot: SourceOfTruth = Depends(get_sot)):
    """Validate, then generate configs for every switch in the rack."""
    ctx = load_rack(rack_id, sot)
    issues = validator.validate(ctx)
    if validator.has_errors(issues):
        log.warning("render blocked for %s: %d issue(s)", rack_id, len(issues))
        raise HTTPException(422, {"message": "rack data failed validation",
                                  "issues": [i.to_dict() for i in issues]})
    configs = renderer.render_rack(ctx)
    log.info("rendered %d config(s) for %s", len(configs), rack_id)
    return {"rack_id": rack_id, "warnings": [i.to_dict() for i in issues], "configs": configs}


@app.get("/api/v1/day0/racks/{rack_id}/devices/{device}/config",
         response_class=PlainTextResponse, tags=["day-0"])
def device_config(rack_id: str, device: str, sot: SourceOfTruth = Depends(get_sot)):
    """Plain-text config for one switch — what a Zero Touch Provisioning boot script would download."""
    ctx = load_rack(rack_id, sot)
    if validator.has_errors(validator.validate(ctx)):
        raise HTTPException(422, "rack data failed validation")
    if ctx.device(device) is None:
        raise HTTPException(404, f"device '{device}' not in rack '{rack_id}'")
    return renderer.render_rack(ctx)[device]


# --- Day-2 ------------------------------------------------------------------
@app.post("/api/v1/day2/drift", tags=["day-2"])
def check_drift(body: DriftRequest, sot: SourceOfTruth = Depends(get_sot)):
    ctx = load_rack(body.rack_id, sot)
    if ctx.device(body.device) is None:
        raise HTTPException(404, f"device '{body.device}' not in rack '{body.rack_id}'")
    intended = renderer.render_rack(ctx)[body.device]
    report = drift.detect_drift(body.device, intended, body.running_config)
    if not report.in_sync:
        log.warning("drift detected on %s", body.device)
    return report.to_dict()


# --- monitoring -------------------------------------------------------------
@app.post("/api/v1/monitoring/anomalies", tags=["monitoring"])
def find_anomalies(body: AnomalyRequest):
    samples = [s.model_dump() for s in body.samples]
    found = anomaly.detect_anomalies(samples, body.threshold, body.window, body.min_scale)
    return {"checked": len(samples), "anomaly_count": len(found), "anomalies": found}
