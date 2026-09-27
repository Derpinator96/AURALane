"""Gate brain studies before they enter the demo fixture, on their reference labels.

    python scripts/validate_corpus.py [studies dir]

Default studies dir: _external/brainmri/data/studies (read only). Prints one row
per study, verdict and reason; nothing is dropped silently.
scripts/make_fixtures.py calls validate() and never turns a refused study into
a worklist row. It records each refusal in fixtures/worklist.meta.json.

This is a data-provenance gate for the demo corpus, not part of the pipeline.
Reference labels (ground truth) do not exist at inference time; a pipeline
that behaved differently when a label happened to be present would be a demo
that does not match production. Triage is untouched.

A study with a reference label is refused when:
  - the label cannot be read, or its shape differs from the study's T1c
  - the label holds fewer data bytes than its declared dimensions need
    (implausibly small for its dimensions, e.g. a truncated file)
  - its values are not one of the two BraTS conventions, {0,1,2,4} (ET = 4,
    BraTS 2021) or {0,1,2,3} (ET = 3, BraTS 2023); both are accepted
  - its file hash, or its voxel content, matches another study's label. Voxel
    content catches the same label saved compressed, where the file hash
    differs. When one label sits on several studies there is no telling from
    the data which study it belongs to, so every study sharing it is refused.

A study with no reference label is accepted with that stated: there is
nothing to check. Studies that are not MRI are skipped, and listed.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import nibabel as nib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STUDIES = ROOT / "_external" / "brainmri" / "data" / "studies"
CONVENTIONS = {frozenset({0, 1, 2, 4}): "ET=4 (BraTS 2021)",
               frozenset({0, 1, 2, 3}): "ET=3 (BraTS 2023)"}


def _first(study: Path, name: str) -> Path | None:
    hits = sorted((study / "input").glob(f"{name}.nii*"))
    return hits[0] if hits else None


def _data_bytes(path: Path, img) -> int:
    """Bytes of voxel data actually present in the file, after the header.
    img.dataobj.offset is where nibabel starts reading the voxels."""
    raw = gzip.open(path).read() if path.suffix == ".gz" else path.read_bytes()
    return max(0, len(raw) - int(img.dataobj.offset))


def _modality(study: Path) -> str:
    try:
        return json.loads((study / "metadata.json").read_text()).get("modality", "?")
    except (OSError, ValueError):
        return "?"


def validate(studies: Path = STUDIES) -> list[dict]:
    """-> [{study, verdict: ACCEPT|REFUSE|SKIP, reason, convention, file_sha1,
    content_sha1}] for every study directory, in name order."""
    out, by_file, by_content = [], defaultdict(list), defaultdict(list)
    for study in sorted(p for p in Path(studies).iterdir() if p.is_dir()):
        row = {"study": study.name, "verdict": "ACCEPT", "reason": "", "convention": None,
               "file_sha1": None, "content_sha1": None}
        out.append(row)
        if _modality(study) != "MRI":
            row.update(verdict="SKIP", reason=f"not MRI ({_modality(study)})")
            continue
        label, t1c = _first(study, "ground_truth"), _first(study, "t1ce")
        if label is None:
            row["reason"] = "no reference label; nothing to check"
            continue
        row["file_sha1"] = hashlib.sha1(label.read_bytes()).hexdigest()[:12]
        try:
            img = nib.load(label)
            need = int(np.prod(img.shape)) * img.get_data_dtype().itemsize
            have = _data_bytes(label, img)
            if have < need:
                row.update(verdict="REFUSE", reason=f"label holds {have:,} data bytes; its "
                           f"declared shape {img.shape} needs {need:,}")
                continue
            data = np.asarray(img.dataobj)
        except Exception as e:                      # unreadable is a refusal, with the cause
            row.update(verdict="REFUSE", reason=f"label unreadable: {type(e).__name__}: {e}")
            continue
        scan_shape = nib.load(t1c).shape if t1c else None
        if data.ndim != 3 or data.shape != scan_shape:
            row.update(verdict="REFUSE", reason=f"label shape {data.shape} does not match "
                       f"the T1c shape {scan_shape}")
            continue
        values = frozenset(int(v) for v in np.unique(data))
        convention = next((name for allowed, name in CONVENTIONS.items() if values <= allowed), None)
        if convention is None:
            row.update(verdict="REFUSE", reason=f"label values {sorted(values)} fit neither "
                       f"{{0,1,2,4}} nor {{0,1,2,3}}")
            continue
        row["convention"] = convention
        row["content_sha1"] = hashlib.sha1(
            str(data.shape).encode() + np.ascontiguousarray(data.astype(np.uint8)).tobytes()
        ).hexdigest()[:12]
        by_file[row["file_sha1"]].append(row)
        by_content[row["content_sha1"]].append(row)

    for rows in by_content.values():
        if len(rows) < 2:
            continue
        for row in rows:
            others = [r["study"] for r in rows if r is not row]
            same_file = [r["study"] for r in by_file[row["file_sha1"]] if r is not row]
            reason = (f"label voxels identical to {len(others)} other "
                      f"stud{'y' if len(others) == 1 else 'ies'}: {', '.join(others)}")
            if same_file:
                reason += f"; byte-identical file on {', '.join(same_file)}"
            row.update(verdict="REFUSE", reason=reason)
    return out


def table(rows: list[dict]) -> str:
    lines = [f"{'study':16} {'verdict':7} {'convention':18} reason"]
    for r in rows:
        lines.append(f"{r['study']:16} {r['verdict']:7} {r['convention'] or '-':18} {r['reason']}")
    counts = {v: sum(r["verdict"] == v for r in rows) for v in ("ACCEPT", "REFUSE", "SKIP")}
    lines.append(f"{len(rows)} studies: " + ", ".join(f"{n} {v.lower()}" for v, n in counts.items()))
    return "\n".join(lines)


if __name__ == "__main__":
    print(table(validate(Path(sys.argv[1]) if len(sys.argv) > 1 else STUDIES)))
