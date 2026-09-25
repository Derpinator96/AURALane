"""The privacy suite cannot pass by skipping.

The OCR masking tests in sim/edge/test_deid.py skip when the 40-study chest
corpus or Tesseract is missing. A run that goes green because they skipped is
worse than a red one, and a skip count only protects us while someone reads it.

So this one test FAILS when either is missing. The exception is explicit:
set AURALANE_ALLOW_SKIP=1 on a machine that is not meant to have the data (a
cloud VM, CI without the corpus). Then it skips, loudly, like the rest.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "chest" / "studies"
CORPUS_SIZE = 40

pytestmark = pytest.mark.privacy


def _missing() -> list[str]:
    missing = []
    try:
        n = len(json.loads((CORPUS / "manifest.json").read_text()))
    except (OSError, ValueError):
        n = 0
    if n != CORPUS_SIZE:
        missing.append(f"the {CORPUS_SIZE}-study chest corpus at data/chest/studies (found {n}; "
                       f"build it with python data/chest/make_chest_corpus.py)")
    if shutil.which("tesseract") is None:
        missing.append("Tesseract")
    return missing


def test_privacy_corpus_and_ocr_are_present():
    missing = _missing()
    if not missing:
        return
    what = " and ".join(missing)
    if os.environ.get("AURALANE_ALLOW_SKIP") == "1":
        pytest.skip(f"AURALANE_ALLOW_SKIP=1 and missing {what}. NOT VERIFIED: the OCR "
                    f"masking claims in sim/edge/test_deid.py")
    pytest.fail(f"missing {what}, so the privacy tests that need them skipped and "
                f"burned-in masking was NOT verified. Provide them, or set "
                f"AURALANE_ALLOW_SKIP=1 if this machine is deliberately without them.",
                pytrace=False)


def test_gate_passes_when_corpus_and_ocr_exist(tmp_path, monkeypatch):
    """The gate is satisfiable: 40 manifest entries and a tesseract binary."""
    (tmp_path / "manifest.json").write_text(json.dumps([{}] * CORPUS_SIZE))
    monkeypatch.setattr(sys.modules[__name__], "CORPUS", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    assert _missing() == []
    (tmp_path / "manifest.json").write_text(json.dumps([{}] * 39))
    assert "found 39" in _missing()[0]
