"""The identity map. The only place a patient name exists in this system.

This file lives on the hospital's own machine, inside the edge agent's volume,
and nothing in the cloud can read it. That is the whole architecture in one
sentence: de-identification happens on-premise, so identifiable data never
crosses the network boundary, and re-identification is a deliberate local
lookup rather than a property of the cloud datastore.

The radiologist's browser runs inside the hospital network, so it can call
/resolve to put real names back on screen. The cloud never sees one.

Two guarantees this must provide:

  CONSISTENCY  the same original UID always maps to the same new UID, so a
               study's instances still belong to the same study after
               de-identification and a second copy of the same study does not
               become a second study.

  REVERSIBILITY  a pseudonym resolves back to the original, because a
                 radiologist looking at the top of the queue needs to know
                 which patient it is.

Those two pull in opposite directions from irreversible anonymisation, and
that is intentional. PS3.15 calls this pseudonymisation; the security control
is that the mapping is held by the data controller (the hospital), not by us.
"""
import os
import sqlite3
import threading

from pydicom.uid import generate_uid

# Same private root the generator uses, different branch so de-identified UIDs
# are visibly ours rather than colliding with the source study's.
UID_ROOT = "1.2.826.0.1.3680043.10.1422."

_SCHEMA = """
CREATE TABLE IF NOT EXISTS uids (
    original   TEXT PRIMARY KEY,
    replacement TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS patients (
    original_id   TEXT PRIMARY KEY,
    pseudo_id     TEXT NOT NULL UNIQUE,
    original_name TEXT,
    original_dob  TEXT,
    original_sex  TEXT
);
CREATE TABLE IF NOT EXISTS studies (
    original_uid      TEXT PRIMARY KEY,
    pseudo_uid        TEXT NOT NULL UNIQUE,
    original_patient  TEXT NOT NULL,
    original_accession TEXT,
    pseudo_accession  TEXT,
    original_date     TEXT,
    received_at       TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS studies_by_pseudo ON studies(pseudo_uid);
"""


class IdentityMap:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        with self._connect() as c:
            c.executescript(_SCHEMA)

    def _connect(self):
        c = sqlite3.connect(self._path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    # -- UIDs -------------------------------------------------------------

    def map_uid(self, original):
        """Deterministic, stable replacement for any UID.

        Called for every StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID
        and every UID referenced inside the dataset. Without this the instances
        of one study would scatter across several studies downstream.
        """
        if not original:
            return original
        with self._lock, self._connect() as c:
            row = c.execute("SELECT replacement FROM uids WHERE original = ?",
                            (original,)).fetchone()
            if row:
                return row["replacement"]
            new = generate_uid(prefix=UID_ROOT)
            c.execute("INSERT INTO uids (original, replacement) VALUES (?, ?)",
                      (original, new))
            return new

    # -- Patients ---------------------------------------------------------

    def map_patient(self, original_id, name=None, dob=None, sex=None):
        """Stable pseudonym for a patient, so priors still group together."""
        key = original_id or "UNKNOWN"
        with self._lock, self._connect() as c:
            row = c.execute("SELECT pseudo_id FROM patients WHERE original_id = ?",
                            (key,)).fetchone()
            if row:
                return row["pseudo_id"]
            n = c.execute("SELECT COUNT(*) AS n FROM patients").fetchone()["n"]
            pseudo = f"AUR-{n + 1:06d}"
            c.execute(
                "INSERT INTO patients (original_id, pseudo_id, original_name,"
                " original_dob, original_sex) VALUES (?, ?, ?, ?, ?)",
                (key, pseudo, str(name) if name else None, dob, sex))
            return pseudo

    # -- Studies ----------------------------------------------------------

    def record_study(self, original_uid, pseudo_uid, original_patient,
                     original_accession=None, original_date=None):
        pseudo_accession = "ACC" + pseudo_uid.split(".")[-1][-9:]
        with self._lock, self._connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO studies (original_uid, pseudo_uid,"
                " original_patient, original_accession, pseudo_accession,"
                " original_date) VALUES (?, ?, ?, ?, ?, ?)",
                (original_uid, pseudo_uid, original_patient or "UNKNOWN",
                 original_accession, pseudo_accession, original_date))
        return pseudo_accession

    # -- Resolution -------------------------------------------------------

    def resolve_study(self, pseudo_uid):
        """Pseudonymous study UID -> the identifiers, for in-hospital display.

        Returns None rather than raising when unknown: a worklist row whose
        identity cannot be resolved must still render, showing the pseudonym.
        Failing closed on display would hide a critical study.
        """
        with self._connect() as c:
            s = c.execute("SELECT * FROM studies WHERE pseudo_uid = ?",
                          (pseudo_uid,)).fetchone()
            if not s:
                return None
            p = c.execute("SELECT * FROM patients WHERE original_id = ?",
                          (s["original_patient"],)).fetchone()
            return {
                "study_uid": s["original_uid"],
                "accession": s["original_accession"],
                "study_date": s["original_date"],
                "patient_id": s["original_patient"],
                "patient_name": p["original_name"] if p else None,
                "patient_dob": p["original_dob"] if p else None,
                "patient_sex": p["original_sex"] if p else None,
            }

    def stats(self):
        with self._connect() as c:
            return {
                "patients": c.execute("SELECT COUNT(*) n FROM patients").fetchone()["n"],
                "studies": c.execute("SELECT COUNT(*) n FROM studies").fetchone()["n"],
                "uids": c.execute("SELECT COUNT(*) n FROM uids").fetchone()["n"],
            }
