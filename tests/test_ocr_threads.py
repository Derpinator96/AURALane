"""deidentify_all caps Tesseract's OpenMP threads while OCR runs in parallel,
and only then.

Without the cap, 4 workers were 57 times slower than 1. Left set afterwards,
torch inherited it and the chest Grad-CAM backward pass did not finish in 120 s
(measurements in core/pipeline.py). No Tesseract needed: deidentify is stubbed.
"""
import os
import sys
from pathlib import Path

import core.pipeline as pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim" / "edge"))
import identity  # noqa: E402


def _seen_during(monkeypatch, tmp_path, workers):
    seen = []
    monkeypatch.setattr(pipeline.pydicom, "dcmread", lambda p: object())
    monkeypatch.setattr(pipeline.deid, "deidentify",
                        lambda ds, ident: seen.append(os.environ.get("OMP_THREAD_LIMIT")) or {})
    pipeline.deidentify_all(["a", "b"], identity.IdentityMap(str(tmp_path / "i.db")),
                            workers=workers)
    return seen


def test_parallel_caps_omp_while_ocr_runs_and_restores_after(monkeypatch, tmp_path):
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    assert _seen_during(monkeypatch, tmp_path, 4) == ["1", "1"]
    assert "OMP_THREAD_LIMIT" not in os.environ


def test_serial_leaves_environment_alone(monkeypatch, tmp_path):
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    assert _seen_during(monkeypatch, tmp_path, 1) == [None, None]
    assert "OMP_THREAD_LIMIT" not in os.environ


def test_operator_setting_is_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("OMP_THREAD_LIMIT", "2")
    assert _seen_during(monkeypatch, tmp_path, 4) == ["2", "2"]
    assert os.environ["OMP_THREAD_LIMIT"] == "2"
