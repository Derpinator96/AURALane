"""The demo display layer: fictional names for the corpus generator's placeholder patients, and for nobody
else. A name is shown only if the source record carried one; nothing is invented for a record without."""
import hashlib
import os
import pathlib
import sqlite3

import numpy as np
import pytest
import pydicom
from fastapi.testclient import TestClient

from core import own_uploads
from core.api import create_app
from core.providers.fixture import BLOB, FixtureDatastore, FixtureTable
from core.providers.local import DevAuth, FileBlob, TemplateLLM
from sim.edge import display_names, identity

R1, R2 = "radiologist-1@dev.auralane.local", "radiologist-2@dev.auralane.local"


# -- display_identity --------------------------------------------------------------
def test_a_placeholder_patient_gets_a_demo_identity_marked_as_such():
    e = display_names.display_identity("SIMID-000042", "SIM^PATIENT^0042", "19710405", "F")
    assert e["source"] == "demo-layer" and e["sex"] == "F" and e["dob"] == "1971-04-05"
    first, last = e["name"].split(" ")
    assert first in display_names.FEMALE and last in display_names.SURNAMES


def test_the_name_is_deterministic_and_follows_the_recorded_sex_when_there_is_one():
    a = display_names.display_identity("SIMID-000042", "SIM^PATIENT^0042", sex="M")
    assert a == display_names.display_identity("SIMID-000042", "SIM^PATIENT^0042", sex="M")
    assert a["name"].split(" ")[0] in display_names.MALE
    names = {display_names.display_identity(f"SIMID-{i:06d}", f"SIM^PATIENT^{i:04d}")["name"] for i in range(1, 200)}
    assert len(names) > 100                                     # spread, not a handful of names
    assert display_names.display_identity("SIMID-000042", "SIM^PATIENT^0042", sex="F")["name"] != a["name"]


def test_birth_date_and_sex_are_only_the_identity_maps_never_generated():
    e = display_names.display_identity("SIMID-000001", "SIM^PATIENT^0001")
    assert e["dob"] is None and e["sex"] is None
    for bad in ("", "1971", "19711340", "abcdefgh", None):
        assert display_names.display_identity("SIMID-000001", "SIM^PATIENT^0001", bad, "X")["dob"] is None
    assert display_names.display_identity("SIMID-000001", "SIM^PATIENT^0001", None, "x")["sex"] is None


@pytest.mark.parametrize("original_name", [
    None, "", " ", "   ", "\n",                                # no name
    "CQ500CT419 CQ500CT419", "CQ500-CT-5",                     # a dataset ID, not a person
    "ID_aeee6c28", "ID_0dc7645c14",                            # the RSNA head CTs' IDs
    "SIM^PATIENT^", "SIM^PATIENT^12A", "sim^patient^0042", "SIM^PATIENT^0042 ", " SIM^PATIENT^0042",
    "SIM^PATIENT^0042^MD", "XSIM^PATIENT^0042", "SIM^REFERRER^A", "ANONYMIZED", "Meera Nambiar",
    "UPLOAD-1a2b3c4d", 42, b"SIM^PATIENT^0042",
])
def test_a_record_without_a_placeholder_name_gets_no_name(original_name):
    assert display_names.display_identity("ID_aeee6c28", original_name, "19710405", "F") is None


def test_no_name_is_made_without_the_gate_being_passed(monkeypatch):
    """Nothing can call the name maker for an input whose original_name is null, empty or not a placeholder,
    and no public function here makes a name from an ID alone."""
    calls = []
    monkeypatch.setattr(display_names, "_fictional_name", lambda *a: calls.append(a) or "Never Shown")
    for name in (None, "", "  ", "CQ500-CT-419", "ID_xxxxxxxx", "SIM^PATIENT^"):
        assert display_names.display_identity("ID_aeee6c28", name, "19710405", "M") is None
        assert display_names.display_identity(None, name) is None
    assert display_names.display_identity(None, "SIM^PATIENT^0001") is None           # and no ID, no seed
    assert display_names.display_identity("", "SIM^PATIENT^0001") is None
    assert display_names.resolve([{"pseudo_id": "AUR-000001", "original_id": "X", "original_name": None},
                                  {"pseudo_id": "AUR-000002", "original_id": "X", "original_name": ""}]) == {}
    assert calls == []
    public = {n for n, f in vars(display_names).items() if callable(f) and not n.startswith("_")
              and getattr(f, "__module__", None) == display_names.__name__}
    assert public == {"display_identity", "resolve"}
    assert display_names.display_identity("SIMID-000001", "SIM^PATIENT^0001")["name"] == "Never Shown"
    assert len(calls) == 1


def test_no_function_in_the_edge_package_makes_a_name_from_a_null_or_empty_one():
    """Through the identity map too: a patient stored with no name is never displayable."""
    import inspect
    for fn in (display_names.display_identity,):
        assert "original_name" in inspect.signature(fn).parameters
    assert display_names.resolve([{"pseudo_id": "AUR-000009", "original_id": "SIMID-000009",
                                   "original_name": name, "original_dob": "19800101", "original_sex": "F"}
                                  for name in (None, "")]) == {}


# -- the identity map, read only -----------------------------------------------------
@pytest.fixture
def idmap(tmp_path):
    """An identity map holding one patient of each kind the demo has."""
    path = str(tmp_path / "identity.db")
    m = identity.IdentityMap(path)
    pseudo = {
        "demo": m.map_patient("SIMID-000042", "SIM^PATIENT^0042", "19710405", "F"),
        "rsna": m.map_patient("ID_aeee6c28", None, None, None),          # no PatientName in the file
        "cq500": m.map_patient("CQ500CT419", "CQ500CT419 CQ500CT419", None, None),
        "idname": m.map_patient("ID_bbbb1111", "ID_bbbb1111", None, None),
        "blank": m.map_patient("ID_cccc2222", "", None, None),
    }
    # An uploaded image, as the pipeline's de-identifier hands it to the map: no name, no dob, no sex.
    img = pydicom.dcmread(own_uploads.wrap_image(_png(tmp_path), tmp_path / "img.dcm"))
    pseudo["image"] = m.map_patient(str(img.PatientID), str(img.PatientName or ""), str(img.PatientBirthDate) or None,
                                    str(img.PatientSex) or None)
    return path, pseudo


def _png(folder):
    from PIL import Image
    p = folder / "scan.png"
    Image.fromarray(np.tile(np.arange(64, dtype=np.uint8), (64, 1))).save(p)
    return p


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_resolve_returns_an_entry_only_for_the_placeholder_patient(idmap):
    path, pseudo = idmap
    before = _sha(path)
    found = display_names.resolve(identity.lookup_patients(path, list(pseudo.values())))
    assert set(found) == {pseudo["demo"]}
    e = found[pseudo["demo"]]
    assert e["source"] == "demo-layer" and e["dob"] == "1971-04-05" and e["sex"] == "F" and e["name"]
    for kind in ("rsna", "cq500", "idname", "blank", "image"):
        assert pseudo[kind] not in found, kind
    assert _sha(path) == before                                   # identity.db is never modified


def test_the_lookup_is_read_only_and_a_missing_map_is_just_empty(tmp_path, idmap):
    path, pseudo = idmap
    with pytest.raises(sqlite3.OperationalError):                 # the connection really is read only
        c = sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        c.execute("DELETE FROM patients")
    assert identity.lookup_patients(tmp_path / "none.db", ["AUR-000001"]) == []
    assert identity.lookup_patients(path, []) == []
    assert identity.lookup_patients(path, ["AUR-999999"]) == []


# -- /api/resolve ----------------------------------------------------------------------
@pytest.fixture
def api(tmp_path, idmap, monkeypatch):
    path, pseudo = idmap
    import core.run as run
    monkeypatch.setattr(run, "IDENTITY_DB", pathlib.Path(path))
    auth = DevAuth(secret=os.urandom(32).hex(), password=os.urandom(8).hex())
    table = FixtureTable()
    rows = table.scan("worklist")
    for row, (kind, pid) in zip(rows, pseudo.items()):
        row["patient_id"], row["assigned_to"], row["assigned_name"] = pid, R1, "Reader 1"
        table.put_item("worklist", row)
    p = {"runtime": "local", "blob": FileBlob(BLOB, url_base="/api/blob"), "datastore": FixtureDatastore(table),
         "table": table, "auth": auth, "llm": TemplateLLM(), "worklist_scope": "own",
         "resolver": run._resolver("local")}
    client = TestClient(create_app(p))
    client.h = lambda user: {"Authorization": f"Bearer {auth.issue(user)}"}
    client.pseudo, client.table = pseudo, table
    return client


def test_resolve_names_the_demo_patient_and_leaves_out_everyone_else(api):
    ids = list(api.pseudo.values())
    r = api.post("/api/resolve", json={"ids": ids}, headers=api.h("radiologist-1"))
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True and set(body["patients"]) == {api.pseudo["demo"]}
    assert body["patients"][api.pseudo["demo"]]["source"] == "demo-layer"
    # An id with no name is left out, not an error; so are ids nobody has heard of.
    r = api.post("/api/resolve", json={"ids": [api.pseudo["rsna"], api.pseudo["cq500"], "AUR-424242"]},
                 headers=api.h("radiologist-1"))
    assert r.status_code == 200 and r.json()["patients"] == {}


def test_a_reader_is_named_only_the_patients_of_studies_they_may_open(api):
    ids = list(api.pseudo.values())
    assert api.post("/api/resolve", json={"ids": ids}, headers=api.h("radiologist-2")).json()["patients"] == {}
    assert api.post("/api/resolve", json={"ids": ids}).status_code == 401
    assert api.post("/api/resolve", json={"ids": ids}, headers=api.h("admin")).status_code == 403


def test_resolving_is_audited_with_counts_and_no_names(api):
    api.post("/api/resolve", json={"ids": list(api.pseudo.values())}, headers=api.h("radiologist-1"))
    events = [e for e in api.table.query("audit", study="-") if e["action"] == "resolve_names"]
    assert len(events) == 1 and events[0]["detail"] == {"requested": len(api.pseudo), "resolved": 1}
    assert not any(n in str(events[0]) for n in display_names.SURNAMES)


def test_where_there_is_no_identity_map_the_answer_is_empty_not_an_error(tmp_path):
    from core.run import _resolver
    assert _resolver("aws") is None and _resolver("fixture") is None
    auth = DevAuth(secret=os.urandom(32).hex(), password=os.urandom(8).hex())
    table = FixtureTable()
    p = {"runtime": "aws", "blob": FileBlob(BLOB, url_base="/api/blob"), "datastore": FixtureDatastore(table),
         "table": table, "auth": auth, "llm": TemplateLLM()}
    c = TestClient(create_app(p))
    r = c.post("/api/resolve", json={"ids": ["AUR-000001"]}, headers={"Authorization": f"Bearer {auth.issue('radiologist-1')}"})
    assert r.status_code == 200 and r.json() == {"disclaimer": "NON-DIAGNOSTIC; DECISION SUPPORT ONLY",
                                                 "available": False, "patients": {}}
