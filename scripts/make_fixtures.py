"""Build the fixture worklist the web app runs against without the corpus.

    python scripts/make_fixtures.py

Writes fixtures/worklist.json, the sample frame under client/public/fixtures/,
and Grad-CAM overlays under fixtures/blob/.
Run AURALANE_RUNTIME=fixture python -m core.run serve to serve them.

Every number in a fixture row is a real computation, and each row says where
it came from in its "source" field:

  chest   15 studies from scores.json, three per outcome (CRITICAL, URGENT,
          ABSTAIN, EXPEDITED, ROUTINE), taken in scores.json order. Their
          triage output is copied as stored: TorchXRayVision on NIH
          ChestX-ray14 images, scored by triage.py. scores.json keeps only the
          top three signals per study, so findings holds those three.
  brain   the four distinct real metrics.json cases from Shaurya's MONAI
          pipeline (_external/brainmri), through adapters.brats and triage.
          Brain volume is counted from each case's own T1c input.

Assigned here, not computed, and labelled as such in each row: the arrival
time (one every 3 minutes from 08:00 UTC, in a fixed shuffled order) and the
pseudonymous patient ID (FIXTURE-nnnn).

The sample frame is TorchXRayVision's public example image
(shaurya-webapp/tests/16747_3_1.jpg) wrapped as CR DICOM by
sim/generator/make_dicom.py, stored as its raw pixel bytes plus its DICOM
header, which is what a WADO-RS frame request returns. Every fixture chest row
displays this one image; it is not the image the row's numbers were computed
from.

Each chest row's Grad-CAM overlay is computed on that sample image for the
row's own driver finding (the one that set its lane in scores.json), with
TorchXRayVision, so the heat sits on the image actually shown. Each row's
evidence says so. Needs torch and the DenseNet weights.
"""
from __future__ import annotations

import datetime
import json
import random
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sim" / "generator"))

from adapters import brats                  # noqa: E402
from core.registry import Registry, rank    # noqa: E402
from core.types import Findings             # noqa: E402
import make_dicom                           # noqa: E402

OUT = ROOT / "fixtures" / "worklist.json"
FRAME = ROOT / "client" / "public" / "fixtures" / "frames" / "sample-cr.frame1.raw"
FRAME_URL = "/fixtures/frames/sample-cr.frame1.raw"
BLOB = ROOT / "fixtures" / "blob"
SAMPLE = ROOT / "shaurya-webapp" / "tests" / "16747_3_1.jpg"
BRAIN = ROOT / "_external" / "brainmri" / "data" / "studies"
BRAIN_CASES = ["00000057", "MRI-1790025179", "MRI-1790070297", "MRI-1790081977"]
PER_LANE = 3


def sample_frame():
    """Write the one fixture frame; return (series entry, the dataset)."""
    img = Image.open(SAMPLE).convert("L")
    img.thumbnail((512, 512))
    when = datetime.datetime(2026, 9, 25, 8, 0, 0)
    ident = make_dicom.make_identity(8999, random.Random(1), when, False)
    ds = make_dicom.build_instance(np.asarray(img), 255, ident, when, SAMPLE.name)
    ds.PatientName, ds.PatientID = "FIXTURE^SAMPLE", "FIXTURE-SAMPLE"
    FRAME.parent.mkdir(parents=True, exist_ok=True)
    for old in FRAME.parent.glob("sample-cr*"):
        old.unlink()
    FRAME.write_bytes(ds.PixelData)
    header = ds.to_json_dict()
    header.pop("7FE00010", None)
    return ({"series_uid": str(ds.SeriesInstanceUID), "number": 1, "description": "PA",
             "instance_count": 1, "instance_uids": [str(ds.SOPInstanceUID)],
             "frame_url": FRAME_URL, "metadata": [header]}, ds)


def gradcam_for(ds, drivers) -> dict:
    """{driver: evidence} for the sample image, one Grad-CAM per driver."""
    import io
    import imaging
    import torchxrayvision as xrv
    from pytorch_grad_cam import GradCAM
    from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget
    from core.providers.local.inference import (_png_bytes, _slug, crop_box, heat_coverage,
                                                render_gradcam, render_heat_layer)
    model = xrv.models.DenseNet(weights="densenet121-res224-all")
    x = imaging.to_model_input(io.BytesIO(_png_bytes(ds.pixel_array)))
    out = {}
    for driver in sorted(drivers):
        target = ClassifierOutputTarget(list(model.pathologies).index(driver))
        with GradCAM(model=model, target_layers=[model.features]) as cam:
            heat = cam(input_tensor=x, targets=[target])[0]
        stem = f"evidence/fixture-sample/gradcam_{_slug(driver)}"
        (BLOB / stem).parent.mkdir(parents=True, exist_ok=True)
        (BLOB / f"{stem}.png").write_bytes(render_gradcam(x[0, 0].numpy(), heat, driver))
        (BLOB / f"{stem}_layer.png").write_bytes(render_heat_layer(heat))
        out[driver] = {
            "gradcam_png": f"{stem}.png", "gradcam_layer_png": f"{stem}_layer.png",
            "gradcam_box": crop_box(*ds.pixel_array.shape), "gradcam_finding": driver,
            "gradcam_coverage": heat_coverage(heat),
            "gradcam_note": (f"Fixture: Grad-CAM of the public sample image for {driver}, "
                             f"the finding that set this row's lane. Not this study's image."),
        }
    return out


def chest_rows(series) -> list[dict]:
    studies = json.loads((ROOT / "scores.json").read_text())["studies"]
    rows = []
    for lane in ("CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE"):
        for s in [s for s in studies if s["lane"] == lane][:PER_LANE]:
            triage = {k: v for k, v in s.items() if k not in ("id", "filename", "image")}
            rows.append({
                "study": f"fixture-cr-{s['id']}", "modality": "CR",
                "model_id": "cxr-densenet-v1", "status": "SCORED", "lane": s["lane"],
                "triage": triage,
                "findings": {t["name"]: t["signal"] for t in s["top_findings"]},
                "evidence": {}, "error": None, "series": [series],
                "source": (f"Fixture. Numbers: scores.json {s['id']} ({s['filename']}, NIH "
                           f"ChestX-ray14), TorchXRayVision scored by triage.py; top 3 of 18 "
                           f"signals stored. Image shown: public sample, not this study. "
                           f"Arrival time and patient ID assigned by make_fixtures.py."),
            })
    return rows


def brain_rows() -> list[dict]:
    entry = Registry().get("brain-brats-monai-v0.5.4")
    rows = []
    for case in BRAIN_CASES:
        m = json.loads((BRAIN / case / "output" / "metrics.json").read_text())
        t1c = nib.load(next((BRAIN / case / "input").glob("t1ce.nii*")))
        brain_cm3 = (float((np.asarray(t1c.dataobj) > 0).sum())
                     * float(np.prod(t1c.header.get_zooms()[:3])) / 1000)
        lr = [i for i, c in enumerate(m["orientation"]) if c in "LR"][0]
        findings, _ = brats.findings_from_metrics(m, entry, brain_cm3, t1c.shape[lr])
        t = rank(Findings(findings), entry)
        rows.append({
            "study": f"fixture-mr-{case}", "modality": "MR", "model_id": entry["id"],
            "status": "SCORED", "lane": t["lane"], "triage": t, "findings": findings,
            "evidence": {}, "error": None,
            "series": [{"series_uid": f"fixture-mr-{case}-{n}", "number": n,
                        "description": d, "instance_count": 0, "instance_uids": []}
                       for n, d in enumerate(("T1C", "T1", "T2", "FLAIR"), 1)],
            "source": (f"Fixture. Numbers: Shaurya's recorded MONAI output for case {case} "
                       f"(metrics.json) through adapters/brats.py and triage.py. No images "
                       f"in fixture mode. Arrival time and patient ID assigned by "
                       f"make_fixtures.py."),
        })
    return rows


def main() -> int:
    series, ds = sample_frame()
    chest = chest_rows(series)
    cams = gradcam_for(ds, {r["triage"]["driver"] for r in chest})
    for r in chest:
        r["evidence"] = cams[r["triage"]["driver"]]
    rows = chest + brain_rows()
    order = list(range(len(rows)))
    random.Random(7).shuffle(order)
    start = datetime.datetime(2026, 9, 25, 8, 0, 0, tzinfo=datetime.timezone.utc)
    for n, i in enumerate(order):
        rows[i]["created_at"] = (start + datetime.timedelta(minutes=3 * n)).isoformat()
        rows[i]["patient_id"] = f"FIXTURE-{n + 1:04d}"
        rows[i]["run_id"] = "fixture"
        rows[i]["datastore_id"] = "fixture"
        rows[i]["study_date"] = "20260925"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=1) + "\n")
    lanes = {}
    for r in rows:
        lanes[r["lane"]] = lanes.get(r["lane"], 0) + 1
    print(f"wrote {len(rows)} rows to {OUT.relative_to(ROOT)}: {lanes}")
    print(f"wrote {FRAME.relative_to(ROOT)} ({FRAME.stat().st_size:,} bytes)")
    print(f"wrote {len(cams)} Grad-CAM overlays under {BLOB.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
