"""scripts/validate_corpus.py on synthetic studies built in tmp_path."""
import gzip
import importlib.util
import json
import shutil
from pathlib import Path

import nibabel as nib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_corpus", ROOT / "scripts" / "validate_corpus.py")
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)

SHAPE = (8, 8, 6)


def _scan(seed):
    return np.random.default_rng(seed).integers(1, 100, SHAPE).astype(np.int16)


def _study(root, name, label=None, modality="MRI", label_name="ground_truth.nii", seed=0,
           created="2026-09-21T00:00:00+00:00"):
    d = root / name / "input"
    d.mkdir(parents=True)
    (root / name / "metadata.json").write_text(json.dumps({"modality": modality,
                                                           "created_at": created}))
    nib.save(nib.Nifti1Image(_scan(seed), np.eye(4)), d / "t1ce.nii")
    if label is not None:
        nib.save(nib.Nifti1Image(label, np.eye(4)), d / label_name)
    return d


def _label(et=4, seed=0):
    a = np.zeros(SHAPE, np.uint8)
    a[2:5, 2:5, 1:4] = 2
    a[3, 3, 2] = et
    a[2, 2, 1 + seed % 3] = 1
    return a


def _source(root, name, seed, label):
    """A source case, as in separated_patients: its own scans and label."""
    d = root / name
    d.mkdir(parents=True)
    nib.save(nib.Nifti1Image(_scan(seed).astype(np.float32), np.eye(4)), d / f"{name}_t1ce.nii")
    nib.save(nib.Nifti1Image(label.astype(np.float32), np.eye(4)), d / f"{name}_seg.nii")


def _verdicts(root, sources=()):
    # sources is always explicit: no test reads the real source directories.
    return {r["study"]: r for r in vc.validate(root, sources=list(sources))}


def test_both_et_conventions_are_accepted(tmp_path):
    _study(tmp_path, "a", _label(et=4, seed=0), seed=0)
    _study(tmp_path, "b", _label(et=3, seed=1), seed=1)
    v = _verdicts(tmp_path)
    assert v["a"]["verdict"] == v["b"]["verdict"] == "ACCEPT"
    assert v["a"]["convention"].startswith("ET=4") and v["b"]["convention"].startswith("ET=3")


def test_mixed_or_unknown_label_values_are_refused(tmp_path):
    bad = _label(et=4)
    bad[0, 0, 0] = 3                                  # 3 and 4 together
    _study(tmp_path, "mixed", bad)
    assert _verdicts(tmp_path)["mixed"]["verdict"] == "REFUSE"


def _shared_corpus(tmp_path):
    studies = tmp_path / "studies"
    shared = _label()
    _study(studies, "orig", shared, seed=0, created="2026-09-18T00:00:00+00:00")
    _study(studies, "copy", shared, seed=1)          # another patient's scans, same label file
    d = _study(studies, "gz", None, seed=2)          # same voxels, compressed, other scans
    nib.save(nib.Nifti1Image(shared, np.eye(4)), d / "ground_truth.nii.gz")
    d = _study(studies, "reupload", None, seed=0,    # the owner's own scans, uploaded later
               created="2026-09-21T00:00:00+00:00")
    nib.save(nib.Nifti1Image(shared, np.eye(4)), d / "ground_truth.nii.gz")
    _study(studies, "own", _label(seed=1), seed=3)
    return studies, shared


def test_a_shared_label_stays_with_the_study_its_source_proves_owns_it(tmp_path):
    studies, shared = _shared_corpus(tmp_path)
    _source(tmp_path / "sources", "case_a", seed=0, label=shared)      # orig's scans and label
    v = _verdicts(studies, [tmp_path / "sources"])
    assert v["orig"]["verdict"] == "ACCEPT" and v["orig"]["provenance"] == "sources/case_a"
    assert v["reupload"]["verdict"] == "REFUSE" and "duplicate upload" in v["reupload"]["reason"]
    assert "already present as orig" in v["reupload"]["reason"]        # earliest upload kept
    for s in ("copy", "gz"):
        assert v[s]["verdict"] == "REFUSE" and "belongs to source case sources/case_a" in v[s]["reason"]
    assert v["gz"]["file_sha1"] != v["orig"]["file_sha1"]              # caught by content, not file
    assert v["own"]["verdict"] == "ACCEPT"


def test_a_shared_label_with_no_matching_source_refuses_everyone(tmp_path):
    studies, _ = _shared_corpus(tmp_path)
    v = _verdicts(studies)                                             # no source cases at all
    assert [v[s]["verdict"] for s in ("orig", "copy", "gz", "reupload")] == ["REFUSE"] * 4
    assert "owner cannot be shown" in v["orig"]["reason"]
    assert v["own"]["verdict"] == "ACCEPT"


def test_provenance_is_by_voxels_across_file_types(tmp_path):
    lab = _label(seed=2)
    _study(tmp_path / "studies", "a", lab, seed=5)                    # int16 scans, uint8 label
    _source(tmp_path / "src", "p9", seed=5, label=lab)                # float32 copies
    assert _verdicts(tmp_path / "studies", [tmp_path / "src"])["a"]["provenance"] == "src/p9"


def test_label_too_small_for_its_dimensions_is_refused(tmp_path):
    d = _study(tmp_path, "trunc", _label())
    raw = (d / "ground_truth.nii").read_bytes()
    (d / "ground_truth.nii").write_bytes(raw[:-40])            # truncated voxel data
    v = _verdicts(tmp_path)["trunc"]
    assert v["verdict"] == "REFUSE" and "data bytes" in v["reason"]


def test_label_shape_must_match_the_scans(tmp_path):
    _study(tmp_path, "flat", np.zeros(SHAPE[:2], np.float32))
    v = _verdicts(tmp_path)["flat"]
    assert v["verdict"] == "REFUSE" and "does not match" in v["reason"]


def test_every_study_is_reported_nothing_dropped(tmp_path):
    _study(tmp_path, "nolabel")
    _study(tmp_path, "xray", modality="CXR")
    rows = vc.validate(tmp_path)
    assert [(r["study"], r["verdict"]) for r in rows] == [("nolabel", "ACCEPT"), ("xray", "SKIP")]
    text = vc.table(rows)
    assert "nolabel" in text and "xray" in text and "2 studies: 1 accept, 0 refuse, 1 skip" in text
