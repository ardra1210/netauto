"""Monitoring: flag anomalous interface metrics with a robust rolling z-score.

Why robust (median + MAD) instead of mean + standard deviation?
Network counters are spiky. One huge spike inflates the mean and the std,
which then hides the *next* spike (masking). The median and the Median
Absolute Deviation barely move when outliers appear, so detection stays
sensitive. 1.4826 * MAD estimates the std for normally distributed data.

Each point is scored only against the window BEFORE it (no look-ahead),
which is how it would run on a live stream.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

MAD_TO_STD = 1.4826


def robust_zscores(values: list[float], window: int = 20, min_scale: float = 1.0) -> list[float | None]:
    """Score each point against the previous `window` points.

    min_scale is a noise floor in the metric's own units. Lesson learned on
    the demo data: error counters are small integers (0,1,2,3...), so the MAD
    is often exactly 0 and *any* change scored as infinite. Flooring the
    scale means "a change of 1 error/min is never an incident by itself".
    """
    scores: list[float | None] = []
    for i, x in enumerate(values):
        history = values[max(0, i - window):i]
        if len(history) < 5:          # not enough history to judge yet
            scores.append(None)
            continue
        med = median(history)
        scale = max(median(abs(h - med) for h in history) * MAD_TO_STD, min_scale)
        scores.append((x - med) / scale)
    return scores


def detect_anomalies(samples: list[dict], threshold: float = 4.0, window: int = 20,
                     min_scale: float = 1.0) -> list[dict]:
    """samples: [{device, interface, metric, timestamp, value}, ...] in any order."""
    series: dict[tuple, list[dict]] = defaultdict(list)
    for s in samples:
        series[(s["device"], s["interface"], s["metric"])].append(s)

    anomalies = []
    for (device, interface, metric), points in series.items():
        points.sort(key=lambda p: p["timestamp"])
        for point, z in zip(points, robust_zscores([p["value"] for p in points], window, min_scale)):
            if z is not None and abs(z) >= threshold:
                anomalies.append({
                    "device": device, "interface": interface, "metric": metric,
                    "timestamp": point["timestamp"], "value": point["value"],
                    "score": round(z, 2),
                    "direction": "spike" if z > 0 else "drop",
                })
    return sorted(anomalies, key=lambda a: (a["timestamp"], a["device"], a["interface"]))
