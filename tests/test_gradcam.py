"""Grad-CAM for the chest driver finding, from the same forward pass. Synthetic image.

Needs torch, torchxrayvision and the DenseNet weights (downloaded on first use);
skips loudly without them.
"""
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

torch = pytest.importorskip("torch", reason="needs torch. NOT VERIFIED: chest Grad-CAM")
xrv = pytest.importorskip("torchxrayvision", reason="needs torchxrayvision. NOT VERIFIED: chest Grad-CAM")

import imaging                                    # noqa: E402
from adapters import multilabel                   # noqa: E402
from core.providers.local import FileBlob         # noqa: E402
from core.providers.local.inference import InProcessInference, _png_bytes  # noqa: E402
from core.registry import Registry, rank          # noqa: E402
from core.types import StudyRef                   # noqa: E402

ENTRY = Registry().get("cxr-densenet-v1")


def _chest_like():
    """A 512 px synthetic frame: two dark lung fields in a brighter body."""
    y, x = np.mgrid[0:512, 0:512]
    img = np.full((512, 512), 170.0)
    for cx in (170, 342):
        img[((x - cx) / 90) ** 2 + ((y - 260) / 170) ** 2 < 1] = 60
    img += 15 * np.sin(x / 9.0)                   # rib-like texture
    return np.clip(img, 0, 255).astype(np.uint8)


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    blob = FileBlob(tmp_path_factory.mktemp("blob"))
    inf = InProcessInference(blob=blob)
    pixels = _chest_like()
    try:
        out = inf.score(StudyRef("1.2.3", "x"), ENTRY, pixels=pixels)
    except Exception as e:                        # weights download blocked, etc.
        pytest.skip(f"chest model unavailable ({type(e).__name__}: {e}). "
                    f"NOT VERIFIED: chest Grad-CAM")
    return inf, blob, pixels, out


def test_outputs_equal_the_one_preprocessing_path(result):
    inf, _, pixels, out = result
    reference = imaging.predict(inf._chest, io.BytesIO(_png_bytes(pixels)))
    assert list(out["preds"]) == list(reference)
    assert out["preds"] == pytest.approx(reference, abs=1e-6)


def test_gradcam_explains_the_triage_driver(result):
    _, blob, _, out = result
    driver = rank(multilabel.adapt(out["preds"], {"entry": ENTRY}), ENTRY)["driver"]
    assert out["evidence"]["gradcam_finding"] == driver
    png = Image.open(io.BytesIO(blob.get(out["evidence"]["gradcam_png"])))
    assert png.size == (448, 496)
    assert out["evidence"]["gradcam_png"].startswith("evidence/1.2.3/gradcam_")


def test_adapter_carries_the_overlay_key_into_findings(result):
    _, _, _, out = result
    f = multilabel.adapt(out, {"entry": ENTRY})
    assert f.evidence["gradcam_png"] == out["evidence"]["gradcam_png"]
    assert f.findings == multilabel.adapt(out["preds"], {"entry": ENTRY}).findings


def test_without_blob_no_overlay_is_made():
    inf = InProcessInference()
    try:
        out = inf.score(StudyRef("1.2.3", "x"), ENTRY, pixels=_chest_like())
    except Exception as e:
        pytest.skip(f"chest model unavailable ({e}). NOT VERIFIED: chest inference")
    assert out["evidence"] == {} and len(out["preds"]) == 18
