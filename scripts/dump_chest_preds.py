"""Write the 18 raw model outputs for every study in scores.json.

    python scripts/dump_chest_preds.py

-> tests/fixtures/chest_preds.json, {filename: {pathology: raw sigmoid}}.

scores.json keeps only triage output (the driver's raw value and the top three
signals, all rounded), so it cannot be re-scored from itself. This is the input
tests/test_triage_regression.py needs to re-score the whole corpus. Same model,
same imaging.predict, same 5-decimal rounding as prepare.py.

Needs torch, torchxrayvision and the NIH PNGs in images/.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import imaging                       # noqa: E402  (pulls in torch)
import torchxrayvision as xrv        # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "chest_preds.json"


def main():
    studies = json.loads((ROOT / "scores.json").read_text())["studies"]
    model = xrv.models.DenseNet(weights="densenet121-res224-all")
    out, missing = {}, []
    for i, s in enumerate(studies, 1):
        path = ROOT / s["image"]
        if not path.exists():
            missing.append(s["filename"])
            continue
        preds = imaging.predict(model, str(path))
        out[s["filename"]] = {k: round(v, 5) for k, v in preds.items()}
        print(f"  [{i}/{len(studies)}] {s['filename']}")
    if missing:
        sys.exit(f"{len(missing)} images missing from images/, e.g. {missing[:3]}. "
                 f"Nothing written.")
    OUT.write_text(json.dumps(out, indent=1))
    print(f"wrote {len(out)} studies to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
