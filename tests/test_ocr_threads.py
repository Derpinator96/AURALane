"""deidentify_all caps Tesseract's OpenMP threads when it runs workers in parallel.

Without the cap, 4 workers were 57 times slower than 1 on the build container
(see the measurement in core/pipeline.py). No Tesseract needed: nothing is OCRed.
"""
import sys
from pathlib import Path

from core.pipeline import deidentify_all

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim" / "edge"))
import identity  # noqa: E402


def test_parallel_sets_omp_thread_limit(monkeypatch, tmp_path):
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    deidentify_all([], identity.IdentityMap(str(tmp_path / "i.db")), workers=4)
    import os
    assert os.environ["OMP_THREAD_LIMIT"] == "1"


def test_serial_leaves_environment_alone(monkeypatch, tmp_path):
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    deidentify_all([], identity.IdentityMap(str(tmp_path / "i.db")), workers=1)
    import os
    assert "OMP_THREAD_LIMIT" not in os.environ


def test_operator_setting_is_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("OMP_THREAD_LIMIT", "2")
    deidentify_all([], identity.IdentityMap(str(tmp_path / "i.db")), workers=4)
    import os
    assert os.environ["OMP_THREAD_LIMIT"] == "2"
