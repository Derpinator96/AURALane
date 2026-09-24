"""The Orthanc gate: STOW-RS in, QIDO-RS and WADO-RS out, one chest and one brain study.

    docker compose -f docker-compose.local.yml up -d
    python scripts/orthanc_roundtrip.py

If Orthanc rejects a generated object, the generator is wrong. This is the
cheapest place to find out, before HealthImaging, whose write surface is the
same STOW-RS and whose errors are worse.

Requests follow DICOM PS3.18 (DICOMweb): STOW-RS as multipart/related of
application/dicom parts, WADO-RS frames as multipart/related of
application/octet-stream. Orthanc's root is /dicom-web/ (Orthanc book, DICOMweb
plugin). UNVERIFIED: this script has not yet been run against a live Orthanc,
because Docker was not installed when it was written.

Exit code 0 only if every check passes.
"""
import email.parser
import email.policy
import json
import sys
import uuid
from pathlib import Path

import httpx
import pydicom

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8042/dicom-web"
CHEST = ROOT / "data" / "chest" / "studies"
BRAIN = ROOT / "data" / "brain" / "dicom"
BATCH = 50                                   # instances per STOW request

FAILED_SOP_SEQUENCE = "00081198"
TAG = {"study_uid": "0020000D", "series_no": "00200011", "series_desc": "0008103E",
       "n_instances": "00201209", "rows": "00280010", "cols": "00280011"}

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{' ok ' if ok else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    return ok


def value(item, tag):
    v = item.get(tag, {}).get("Value")
    return v[0] if v else None


def stow(client, paths):
    """-> (stored, failed). One multipart/related request per BATCH files."""
    stored = failed = 0
    for i in range(0, len(paths), BATCH):
        boundary = uuid.uuid4().hex
        body = bytearray()
        for p in paths[i:i + BATCH]:
            body += (f"--{boundary}\r\nContent-Type: application/dicom\r\n\r\n").encode()
            body += p.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        r = client.post(f"{BASE}/studies", content=bytes(body), headers={
            "Content-Type": f'multipart/related; type="application/dicom"; boundary={boundary}',
            "Accept": "application/dicom+json"})
        n = len(paths[i:i + BATCH])
        if r.status_code not in (200, 202):
            print(f"         STOW HTTP {r.status_code}: {r.text[:300]}")
            failed += n
            continue
        bad = len(r.json().get(FAILED_SOP_SEQUENCE, {}).get("Value", []))
        failed += bad
        stored += n - bad
        if bad:
            print(f"         STOW refused {bad} instances: "
                  f"{json.dumps(r.json()[FAILED_SOP_SEQUENCE])[:300]}")
    return stored, failed


def qido_has(client, params, study_uid):
    r = client.get(f"{BASE}/studies", params=params, headers={"Accept": "application/dicom+json"})
    if r.status_code == 204:
        return False
    r.raise_for_status()
    return any(value(item, TAG["study_uid"]) == study_uid for item in r.json())


def first_frame(client, study, series, sop):
    """Raw bytes of frame 1, as stored (transfer-syntax=*)."""
    r = client.get(f"{BASE}/studies/{study}/series/{series}/instances/{sop}/frames/1",
                   headers={"Accept": 'multipart/related; type="application/octet-stream"; '
                                      'transfer-syntax=*'})
    r.raise_for_status()
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        f"Content-Type: {r.headers['content-type']}\r\n\r\n".encode() + r.content)
    parts = [p for p in msg.iter_parts()]
    return parts[0].get_payload(decode=True), parts[0].get_content_type()


def round_trip(client, label, root, study_uid, manifest):
    print(f"{label}: study ...{study_uid[-12:]}")
    entries = [e for e in manifest if e["study_uid"] == study_uid]
    paths = [root / e["path"] for e in entries]
    stored, failed = stow(client, paths)
    if not check("STOW-RS", failed == 0, f"{stored}/{len(paths)} stored"):
        return None

    ds = pydicom.dcmread(paths[0], stop_before_pixels=True)
    check("QIDO-RS by modality", qido_has(client, {"ModalitiesInStudy": ds.Modality}, study_uid),
          f"ModalitiesInStudy={ds.Modality}")
    check("QIDO-RS by study date", qido_has(client, {"StudyDate": ds.StudyDate}, study_uid),
          f"StudyDate={ds.StudyDate}")

    local = pydicom.dcmread(paths[0])
    frame, ctype = first_frame(client, study_uid, local.SeriesInstanceUID, local.SOPInstanceUID)
    expected = local.Rows * local.Columns * local.BitsAllocated // 8
    check("WADO-RS frame size", len(frame) == expected,
          f"{len(frame)} bytes, expected {local.Rows}x{local.Columns}x"
          f"{local.BitsAllocated // 8} = {expected} ({ctype})")
    check("WADO-RS frame bytes", frame == local.PixelData,
          "identical to the uploaded PixelData" if frame == local.PixelData else
          "differ from the uploaded PixelData (transcoded?)")
    return entries


def main():
    try:
        httpx.get(f"{BASE}/studies", timeout=3).raise_for_status()
    except Exception as e:
        print(f"Orthanc DICOMweb is not answering at {BASE}: {e}")
        print("  -> docker compose -f docker-compose.local.yml up -d")
        return 2

    chest = json.loads((CHEST / "manifest.json").read_text())
    brain = json.loads((BRAIN / "manifest.json").read_text())

    with httpx.Client(timeout=60) as client:
        round_trip(client, "chest", CHEST, chest[0]["study_uid"], chest)

        study = brain[0]["study_uid"]
        entries = round_trip(client, "brain", BRAIN, study, brain)
        if entries is not None:
            r = client.get(f"{BASE}/studies/{study}/series",
                           params={"includefield": [TAG["series_desc"], TAG["n_instances"]]},
                           headers={"Accept": "application/dicom+json"})
            r.raise_for_status()
            got = sorted((int(value(s, TAG["series_no"])), value(s, TAG["series_desc"]),
                          int(value(s, TAG["n_instances"]))) for s in r.json())
            want = sorted({(e["series_number"], e["series_description"],
                            sum(x["series_uid"] == e["series_uid"] for x in entries))
                           for e in entries})
            check("four series, counts match", got == want,
                  ", ".join(f"{n}:{d}={c}" for n, d, c in got))
            check("series 1 is T1C", bool(got) and got[0][:2] == (1, "T1C"))

    failed = results.count(False)
    print(f"{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
