"""The datastore contract. If this passes for a provider, swapping runtimes is safe.

Parameterised over providers. Today: Orthanc. Prompt 3 appends HealthImaging to
PROVIDERS and every assertion below must pass unchanged. That is why frame bytes
are decoded by what they are (raw little-endian or JPEG 2000 / HTJ2K) and not by
which provider sent them.

Needs the local stack and the two corpora:
    docker compose -f docker-compose.local.yml up -d
    python data/chest/make_chest_corpus.py
    python data/brain/nifti_to_dicom.py --slices 1
"""
import json
from pathlib import Path

import httpx
import numpy as np
import pydicom
import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPORA = {
    "chest": ROOT / "data" / "chest" / "studies",
    "brain": ROOT / "data" / "brain" / "dicom",
}
EXPECTED = {
    # label: (modality, series count, instances per series, series 1 description)
    "chest": ("CR", 1, 1, None),
    "brain": ("MR", 4, 155, "T1C"),
}
J2K_MAGIC = (b"\x00\x00\x00\x0cjP  \r\n\x87\n", b"\xff\x4f\xff\x51")   # JP2 box, raw codestream


def _orthanc():
    from core.providers.local import OrthancDatastore
    ds = OrthancDatastore()
    try:
        ds.http.get(f"{ds.web}/studies", timeout=3).raise_for_status()
    except Exception as e:
        pytest.fail(f"Orthanc DICOMweb not answering at {ds.web}: {e}")
    return ds


PROVIDERS = {"orthanc": _orthanc}
pytestmark = pytest.mark.local_data


def _study_files(label):
    root = CORPORA[label]
    manifest = root / "manifest.json"
    if not manifest.exists():
        pytest.skip(f"needs the {label} corpus at {root} (not in git). NOT VERIFIED: that "
                    f"the datastore round-trips a {label} study (import, metadata, search, "
                    f"frames, frame_url) for this provider")
    entries = json.loads(manifest.read_text())
    uid = entries[0]["study_uid"]
    return uid, [root / e["path"] for e in entries if e["study_uid"] == uid]


def decode_frame(data: bytes, rows: int, cols: int, bits: int) -> np.ndarray:
    if data.startswith(J2K_MAGIC):
        from pylibjpeg import decode
        arr = decode(data)
    else:
        arr = np.frombuffer(data, dtype=np.uint8 if bits == 8 else np.uint16)
        assert arr.size == rows * cols, f"{arr.size} values, expected {rows}x{cols}"
        arr = arr.reshape(rows, cols)
    return arr


def fetch(url: str) -> bytes:
    """GET a frame URL. Accepts a multipart/related WADO-RS answer or a bare body."""
    from core.providers.local.orthanc import FRAME_ACCEPT, parse_multipart
    r = httpx.get(url, headers={"Accept": FRAME_ACCEPT}, timeout=60)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if ctype.startswith("multipart/"):
        parts = parse_multipart(ctype, r.content)
        assert len(parts) == 1
        return parts[0]
    return r.content


@pytest.fixture(scope="module", params=list(PROVIDERS))
def store(request):
    return PROVIDERS[request.param]()


@pytest.fixture(scope="module", params=list(CORPORA))
def imported(request, store):
    label = request.param
    uid, files = _study_files(label)
    ref = store.import_study(files)
    return label, uid, files, ref


def test_import_returns_usable_ref(store, imported):
    label, uid, files, ref = imported
    assert ref.study_uid == uid
    assert ref.datastore_id and ref.datastore_id != uid
    assert store.get_metadata(ref).ref == ref


def test_metadata_shape(store, imported):
    label, uid, files, ref = imported
    modality, n_series, per_series, first = EXPECTED[label]
    src = pydicom.dcmread(files[0], stop_before_pixels=True)
    meta = store.get_metadata(ref)

    assert meta.modality == modality
    assert meta.study_date == src.StudyDate
    assert meta.patient_id == str(src.PatientID)
    assert len(meta.series) == n_series
    assert [s.instance_count for s in meta.series] == [per_series] * n_series
    assert all(len(s.instance_uids) == s.instance_count for s in meta.series)
    assert [s.number for s in meta.series] == list(range(1, n_series + 1))
    if first:
        assert meta.series[0].description == first


def test_search(store, imported):
    label, uid, files, ref = imported
    modality = EXPECTED[label][0]
    date = pydicom.dcmread(files[0], stop_before_pixels=True).StudyDate

    assert uid in {m.ref.study_uid for m in store.search(modality=modality)}
    assert uid in {m.ref.study_uid for m in store.search(study_date=date)}
    wrong = "CT" if modality != "CT" else "US"
    assert store.search(modality=wrong, study_uid=uid) == []
    hit = store.search(modality=modality, study_uid=uid)
    assert len(hit) == 1 and hit[0] == store.get_metadata(ref)


def test_frames(store, imported):
    label, uid, files, ref = imported
    meta = store.get_metadata(ref)
    series = meta.series[0]
    sop = series.instance_uids[0]
    src = next(pydicom.dcmread(f) for f in files
               if pydicom.dcmread(f, stop_before_pixels=True).SOPInstanceUID == sop)

    data = store.get_frame(ref, series.series_uid, sop)
    pixels = decode_frame(data, src.Rows, src.Columns, src.BitsAllocated)
    assert pixels.shape == (src.Rows, src.Columns)
    assert np.array_equal(pixels, src.pixel_array), "frame is not lossless"

    assert fetch(store.frame_url(ref, series.series_uid, sop)) == data
