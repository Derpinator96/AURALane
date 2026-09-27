"""scripts/measure_latency.py renders what the audit trail recorded. Synthetic rows."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("measure_latency", ROOT / "scripts" / "measure_latency.py")
ml = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ml)


def _ev(action, ms, outcome="ok"):
    return {"action": action, "duration_ms": ms, "outcome": outcome, "event_id": action}


def test_table_shows_recorded_durations_failures_and_unreached_steps():
    scored = {"status": "SCORED, URGENT", "gradcam": "yes", "events": [_ev(s, 10.0 * (i + 1))
                                                     for i, s in enumerate(ml.STEPS)]}
    failed = {"status": "FAILED", "events": [_ev("deidentify", 1234.5), _ev("blob_put", 2.0),
                                             _ev("import", 3.0), _ev("prepare_inputs", 7.0),
                                             _ev("infer", 4.0, "failed"),
                                             _ev("persist", 5.0), _ev("blob_delete", 6.0)]}
    page = ml.render([("chest", scored), ("brain", failed)], {"Date": "2026-09-25", "CPU": "x"})

    rows = {line.split("|")[1].strip(): [c.strip() for c in line.split("|")[2:-1]]
            for line in page.splitlines() if line.startswith("| ")}
    assert rows["deidentify"] == ["10.0", "1,234.5"]
    assert rows["prepare_inputs"] == ["40.0", "7.0"]
    assert rows["infer"] == ["50.0", "4.0 (failed)"]
    assert rows["adapt"] == ["60.0", "not reached"]
    assert rows["**total**"] == ["450.0", "1,261.5"]
    assert rows["outcome"] == ["SCORED, URGENT", "FAILED"]
    assert rows["Grad-CAM inside infer"] == ["yes", "not recorded"]
    assert "Awaiting" not in page and "- CPU: x" in page


def test_empty_page_claims_no_measurement():
    page = ml.empty_page()
    assert "No figure on this page has been measured yet" in page
    body = [line for line in page.splitlines()
            if line.startswith("| ") and not line.startswith("| step")]
    cells = {c.strip() for line in body for c in line.split("|")[2:-1]}
    assert cells == {"not measured"}                       # no figure in any cell
    assert (ROOT / "docs" / "LATENCY.md").read_text() == page
