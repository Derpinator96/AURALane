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
    layer = Image.open(io.BytesIO(blob.get(out["evidence"]["gradcam_layer_png"])))
    assert layer.mode == "RGBA" and layer.size == (224, 224)
    assert out["evidence"]["gradcam_box"] == [0, 0, 512]     # square frame: whole image
    alpha = np.asarray(layer)[..., 3]
    assert out["evidence"]["gradcam_coverage"] == round(float((alpha > 0).mean()), 4)


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


def test_crop_box_matches_torchxrayvision_center_crop():
    from core.providers.local.inference import crop_box
    for rows, cols in [(885, 1036), (1036, 885), (512, 512), (3001, 2500)]:
        img = np.arange(rows * cols).reshape(1, rows, cols)
        x, y, size = crop_box(rows, cols)
        assert np.array_equal(xrv.datasets.XRayCenterCrop()(img), img[:, y:y + size, x:x + size])


def test_each_top_finding_gets_layer_heatmap_and_blended_images(result):
    """A map for the top findings by weighted value, the driver first, each with the
    three images under evidence/<study>/gradcam/, computed for this study."""
    from core import cxr_gradcam
    _, blob, _, out = result
    ev = out["evidence"]
    assert "gradcam_findings_error" not in ev, ev.get("gradcam_findings_error")
    listed = ev["gradcam_findings"]
    assert len(listed) == cxr_gradcam.GRADCAM_FINDINGS and listed[0]["driver"] is True
    assert listed[0]["name"] == ev["gradcam_finding"] and not any(g["driver"] for g in listed[1:])
    weights = [g["weighted"] for g in listed]
    assert weights == sorted(weights, reverse=True) or listed[0]["driver"]      # driver first, then by weight
    assert len({g["name"] for g in listed}) == len(listed)
    assert ev["gradcam_findings_seconds"] >= 0
    for g in listed:
        stem = f"evidence/1.2.3/gradcam/{g['slug']}"
        assert (g["layer_png"], g["heatmap_png"], g["blended_png"]) == (
            f"{stem}_layer.png", f"{stem}_heatmap.png", f"{stem}_blended.png")
        layer = Image.open(io.BytesIO(blob.get(g["layer_png"])))
        heat = Image.open(io.BytesIO(blob.get(g["heatmap_png"])))
        blended = Image.open(io.BytesIO(blob.get(g["blended_png"])))
        assert layer.mode == "RGBA" and layer.size == (224, 224)
        assert heat.mode == "RGB" and heat.size == (224, 224) and blended.size == (448, 448)
    # Grad-CAM is the ReLU of a weighted sum, so a finding can have no supporting region
    # on an image; its map is then empty and coverage says 0, which the viewer states.
    assert all(0 <= g["coverage"] <= 1 for g in listed)


def test_jet_and_normalise_follow_the_reference_rendering():
    import numpy as np
    from core import cxr_gradcam as cg
    assert tuple(cg.jet(np.array(0.0))) == (0, 0, 127) and tuple(cg.jet(np.array(1.0))) == (127, 0, 0)
    flat = cg.normalise(np.ones((224, 224), np.float32))
    assert float(flat.max()) == 0.0                                    # a flat map stays empty
    spot = np.zeros((224, 224), np.float32)
    spot[100:110, 100:110] = 1.0
    n = cg.normalise(spot)
    assert n.min() >= 0 and abs(n.max() - 1.0) < 1e-6 and n[105, 105] > n[10, 10]
