from app.anomaly import detect_anomalies, robust_zscores


def series(values, device="leaf1", interface="Ethernet49", metric="input_errors"):
    return [{"device": device, "interface": interface, "metric": metric,
             "timestamp": t, "value": v} for t, v in enumerate(values)]


def test_needs_history_before_scoring():
    assert robust_zscores([1, 2, 3, 4]) == [None] * 4


def test_flat_noise_has_no_anomalies():
    values = [10, 11, 9, 10, 12, 10, 9, 11, 10, 10, 11, 9] * 3
    assert detect_anomalies(series(values)) == []


def test_spike_is_detected_with_direction():
    values = [10, 11, 9, 10, 12, 10, 9, 11, 10, 10, 500, 10, 11]
    found = detect_anomalies(series(values))
    assert [(a["timestamp"], a["direction"]) for a in found] == [(10, "spike")]


def test_drop_is_detected():
    values = [40, 41, 39, 40, 42, 40, 39, 41, 2, 40]
    found = detect_anomalies(series(values, metric="utilization_pct"))
    assert [(a["timestamp"], a["direction"]) for a in found] == [(8, "drop")]


def test_median_is_robust_to_masking():
    """Two spikes in a row: with mean/std the first would hide the second."""
    values = [10, 11, 9, 10, 12, 10, 9, 11, 10, 300, 310, 10]
    stamps = [a["timestamp"] for a in detect_anomalies(series(values))]
    assert stamps == [9, 10]


def test_series_are_independent_and_input_order_does_not_matter():
    a = series([10, 11, 9, 10, 12, 10, 9, 11, 500], interface="Ethernet49")
    b = series([10] * 9, interface="Ethernet50")
    found = detect_anomalies(list(reversed(a + b)))
    assert {(x["interface"], x["timestamp"]) for x in found} == {("Ethernet49", 8)}


def test_noise_floor_stops_integer_counter_false_alarms():
    """Regression test: flat 0-error history used to make '+1 error' score infinity."""
    assert detect_anomalies(series([0, 0, 0, 0, 0, 0, 1, 2, 0, 3])) == []
    found = detect_anomalies(series([0, 0, 0, 0, 0, 0, 50]))
    assert found[0]["score"] == 50.0
