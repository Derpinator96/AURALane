"""Adds the head CT row to fixtures/worklist.json by running the CT model.

    python scripts/make_ct_fixture.py "ct scan data/ID_bd8ef2b128"

Runs core.ct_hemorrhage (Mehak's pipeline in CT_Mehak/triagelane-ct) on one
local study, writes its Grad-CAM evidence under fixtures/blob/evidence/, and
replaces any existing CT row, so every number in the row is the model's.
Needs torch and transformers; the first run downloads the model weights.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import ct_hemorrhage as ct                  # noqa: E402
from core.providers.fixture import BLOB, WORKLIST     # noqa: E402
from core.providers.local.blob import FileBlob        # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.exit(__doc__)
    study_dir = Path(argv[0])
    rsna_id = study_dir.name
    study = f"fixture-ct-{rsna_id.lower()}"
    payloads = [(f.name, f.read_bytes()) for f in sorted(study_dir.iterdir()) if f.is_file()]
    out = ct.score_upload(payloads, FileBlob(BLOB), study)

    row = {
        "study": study,
        "modality": "CT",
        "model_id": ct.MODEL_ID,
        "status": "SCORED",
        "lane": out["lane"],
        "triage": out["triage"],
        "findings": out["findings"],
        "evidence": out["evidence"],
        "error": None,
        "source": (f"RSNA Intracranial Hemorrhage Detection study {rsna_id}, "
                   f"{out['n_slices']} slices, scored by scripts/make_ct_fixture.py."),
        "created_at": "2026-09-25T08:52:00+00:00",
        "patient_id": f"RSNA-{rsna_id}",
        "run_id": "fixture",
        "datastore_id": "fixture",
        "study_date": "20260925",
        "series": [{"series_uid": f"{study}-1", "number": 1,
                    "description": f"Head CT Axial Non-Contrast ({out['n_slices']} slices)",
                    "instance_count": out["n_slices"], "instance_uids": []}],
    }
    rows = [r for r in json.loads(WORKLIST.read_text()) if r.get("modality") != "CT"]
    rows.append(row)
    WORKLIST.write_text(json.dumps(rows, indent=1))
    t = out["triage"]
    print(f"{study}: {out['lane']} acuity {t['acuity']} driver {t['driver']}; "
          f"evidence {sorted(k for k in out['evidence'] if k.endswith('_png'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
