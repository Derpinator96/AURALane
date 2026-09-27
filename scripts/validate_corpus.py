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
  - its voxel content matches another study's label (voxel content, so the same
    label saved compressed is caught although its file hash differs), and this
    study is not the one the label provably belongs to.

On such a collision, the rule is provenance, not a list of names. A study keeps
its label only if its imaging independently matches the label's source: some
source case whose T1c AND segmentation both equal this study's T1c and label,
voxel for voxel. Source cases are read from SOURCES (Shaurya's
separated_patients and our own data/brain/raw), whichever exist. If several
studies match the same source case they are re-uploads of one study; the
earliest upload (metadata.json created_at) is kept and the rest are refused as
duplicates. Every other study sharing the label is refused, with the source
case the label belongs to named. If no source case matches, nobody can be shown
to own the label and all are refused. There is no hardcoded allowlist.

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
# Directories of source cases, one per subdirectory, each with a *t1ce.nii* and a
# *seg.nii* file. Only the ones present on this machine are used, and the
# provenance column says which source matched.
SOURCES = [ROOT / "_external" / "brainmri" / "separated_patients", ROOT / "data" / "brain" / "raw"]
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


def _voxels(data: np.ndarray, dtype) -> str:
    """Content hash of a volume, independent of file format and compression.
    Values are rounded, so int16 and float32 copies of the same scan agree."""
    arr = np.rint(np.asarray(data, dtype=np.float64)).astype(dtype)
    return hashlib.sha1(str(arr.shape).encode() + np.ascontiguousarray(arr).tobytes()).hexdigest()[:12]


def source_index(sources=None) -> dict[tuple[str, str], str]:
    """{(t1ce hash, label hash): source case name} over every source case found."""
    index = {}
    for root in (SOURCES if sources is None else sources):
        root = Path(root)
        if not root.is_dir():
            continue
        for case in sorted(p for p in root.iterdir() if p.is_dir()):
            t1c = sorted(case.glob("*t1ce.nii*"))
            seg = sorted(case.glob("*seg.nii*"))
            if t1c and seg:
                key = (_voxels(nib.load(t1c[0]).dataobj, np.int32),
                       _voxels(nib.load(seg[0]).dataobj, np.uint8))
                index[key] = f"{root.name}/{case.name}"
    return index


def _created(study: Path) -> str:
    try:
        return json.loads((study / "metadata.json").read_text()).get("created_at") or "~"
    except (OSError, ValueError):
        return "~"                                   # sorts after any timestamp


def _modality(study: Path) -> str:
    try:
        return json.loads((study / "metadata.json").read_text()).get("modality", "?")
    except (OSError, ValueError):
        return "?"


def validate(studies: Path = STUDIES, sources=None) -> list[dict]:
    """-> [{study, verdict: ACCEPT|REFUSE|SKIP, reason, convention, provenance,
    file_sha1, content_sha1}] for every study directory, in name order."""
    index = source_index(sources)
    out, by_file, by_content = [], defaultdict(list), defaultdict(list)
    for study in sorted(p for p in Path(studies).iterdir() if p.is_dir()):
        row = {"study": study.name, "verdict": "ACCEPT", "reason": "", "convention": None,
               "provenance": None, "file_sha1": None, "content_sha1": None,
               "_dir": study, "_scan": None}
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
        row["content_sha1"] = _voxels(data, np.uint8)
        row["_scan"] = _voxels(nib.load(t1c).dataobj, np.int32)
        row["provenance"] = index.get((row["_scan"], row["content_sha1"]))
        by_file[row["file_sha1"]].append(row)
        by_content[row["content_sha1"]].append(row)

    for rows in by_content.values():
        if len(rows) < 2:
            continue
        owners = [r for r in rows if r["provenance"]]
        # Several owners are re-uploads of one source case: keep the earliest.
        owners.sort(key=lambda r: (_created(r["_dir"]), r["study"]))
        keep = owners[0] if owners else None
        source = keep["provenance"] if keep else next(
            (name for (scan, lab), name in index.items() if lab == rows[0]["content_sha1"]), None)
        for row in rows:
            others = [r["study"] for r in rows if r is not row]
            if row is keep:
                row["reason"] = (f"label shared with {len(others)} other stud"
                                 f"{'y' if len(others) == 1 else 'ies'}; kept: scans and label "
                                 f"both match source case {source}")
            elif row["provenance"]:
                row.update(verdict="REFUSE", reason=f"duplicate upload of source case {source}, "
                           f"already present as {keep['study']} (earlier upload)")
            elif source:
                row.update(verdict="REFUSE", reason=f"label belongs to source case {source}, whose "
                           f"scans are not this study's; kept on {keep['study'] if keep else 'no study'}")
            else:
                row.update(verdict="REFUSE", reason=f"label shared with {', '.join(others)} and no "
                           f"source case matches it; its owner cannot be shown")
    for row in out:
        row.pop("_dir"), row.pop("_scan")
    return out


def table(rows: list[dict]) -> str:
    lines = [f"{'study':16} {'verdict':7} {'convention':18} {'provenance':36} reason"]
    for r in rows:
        lines.append(f"{r['study']:16} {r['verdict']:7} {r['convention'] or '-':18} "
                     f"{r.get('provenance') or '-':36} {r['reason']}")
    counts = {v: sum(r["verdict"] == v for r in rows) for v in ("ACCEPT", "REFUSE", "SKIP")}
    lines.append(f"{len(rows)} studies: " + ", ".join(f"{n} {v.lower()}" for v, n in counts.items()))
    return "\n".join(lines)


if __name__ == "__main__":
    print(table(validate(Path(sys.argv[1]) if len(sys.argv) > 1 else STUDIES)))
