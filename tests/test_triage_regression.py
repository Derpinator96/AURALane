"""Guards the triage refactor: the registry-backed path must reproduce the old
output exactly. Not approximately. If this fails, the refactor is wrong.

New path: raw sigmoids -> adapters.multilabel.adapt -> core.registry.rank
(triage.rank with the registry entry's urgency weights).
Old path: tests/fixtures/triage_pre_registry.py, triage.py frozen at 71a9ebd.

Compared as serialised JSON, so key order, value types and every rounded digit
must agree.

Two corpora:
  synthetic   20,000 seeded studies spanning every lane and the abstention band.
              Runs anywhere.
  scores.json the committed 1,000-study pool. scores.json stores only triage
              output, not the 18 raw values it was computed from, so re-scoring
              it needs tests/fixtures/chest_preds.json, written by
              scripts/dump_chest_preds.py. Without that file this test FAILS;
              it does not skip.
"""
import importlib.util
import json
import random
from collections import Counter
from pathlib import Path

import pytest

import triage
from adapters import multilabel
from core.registry import Registry, rank

ROOT = Path(__file__).resolve().parents[1]
PREDS = ROOT / "tests" / "fixtures" / "chest_preds.json"
REFERENCE = json.loads((ROOT / "reference.json").read_text())


def _old():
    spec = importlib.util.spec_from_file_location(
        "triage_pre_registry", ROOT / "tests" / "fixtures" / "triage_pre_registry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OLD = _old()
ENTRY = Registry().get("cxr-densenet-v1")


def new_path(preds):
    return rank(multilabel.adapt(preds, {"entry": ENTRY}), ENTRY)


def _synthetic(n=20_000, seed=2026):
    """Raw outputs drawn around each finding's own reference distribution, wide
    enough to reach every lane, rounded to 5 decimals like prepare.py."""
    rng = random.Random(seed)
    for _ in range(n):
        spread = rng.choice((0.5, 1.5, 3.0))
        yield {k: round(min(max(r["mean"] + r["sd"] * rng.gauss(0.8, spread), 1e-4), 1 - 1e-4), 5)
               for k, r in REFERENCE.items()}


def test_urgency_moved_verbatim():
    assert json.dumps(ENTRY["urgency"]) == json.dumps(OLD.URGENCY)
    assert json.dumps(triage.load_urgency()) == json.dumps(OLD.URGENCY)


def test_synthetic_corpus_byte_identical():
    lanes, n = Counter(), 0
    for preds in _synthetic():
        old = json.dumps(OLD.score(preds, REFERENCE))
        assert json.dumps(new_path(preds)) == old, preds
        assert json.dumps(triage.score(preds, REFERENCE)) == old, preds  # server.py / prepare.py path
        lanes[json.loads(old)["lane"]] += 1
        n += 1
    # The corpus must exercise every branch, or identical output proves little.
    assert set(lanes) == {"CRITICAL", "URGENT", "EXPEDITED", "ROUTINE", "ABSTAIN"}, lanes
    assert min(lanes.values()) >= 100, lanes


def test_scores_json_corpus_byte_identical():
    if not PREDS.exists():
        pytest.fail(f"{PREDS.relative_to(ROOT)} is missing. scores.json holds no raw "
                    f"model outputs, so it cannot be re-scored without it. Run "
                    f"python scripts/dump_chest_preds.py (needs torch and images/).")
    preds_by_file = json.loads(PREDS.read_text())
    studies = json.loads((ROOT / "scores.json").read_text())["studies"]
    assert len(preds_by_file) == len(studies)

    mismatched = []
    for s in studies:
        preds = preds_by_file[s["filename"]]
        new = new_path(preds)
        assert json.dumps(new) == json.dumps(OLD.score(preds, REFERENCE)), s["id"]
        stored = {k: v for k, v in s.items() if k not in ("id", "filename", "image")}
        if json.dumps(new) != json.dumps(stored):
            mismatched.append(s["id"])
    assert not mismatched, (
        f"{len(mismatched)} studies differ from scores.json: {mismatched[:20]}. The "
        f"refactor matched the frozen triage on these inputs, so the stored pool and "
        f"the regenerated predictions disagree (scores.json predates the imaging.py "
        f"RGBA fix). Regenerate the pool; do not loosen this test.")
