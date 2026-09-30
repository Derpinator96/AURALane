"""The demo display layer: fictional names for the demo's own placeholder patients, and only those.

The test corpus's generator (sim/generator/make_dicom.py) gives each chest study a placeholder patient,
PatientName SIM^PATIENT^NNNN. A radiologist's screen reads better with a name than with AUR-000042, so this
layer puts a fictional name on those patients and on nobody else.

The rule: a name is shown only if the source record actually carried a name, and never invented for
something that had none. So display_identity() answers only when the identity map's original_name is a
placeholder of that exact form. Everything else gets None, and the client then shows the pseudonym alone:

    an image (PNG, JPEG) wrapped for ingest      it carries no patient
    the RSNA head CTs                            original_name is NULL
    the CQ500 head CTs                           their "name" is a dataset ID, not a person
    any identity-map row with no name            NULL, empty or blank

The fictional name is deterministic (seeded from a hash of the original patient ID, so the same patient has
the same name on every screen and every run) and drawn from the fixed lists below. Date of birth and sex are
the identity map's own when it has them, and never generated. Every entry carries "source": "demo-layer" so it
cannot be mistaken for real data. The identity map is opened read-only and is never modified.

The names are common given names and surnames from several regions, mixed, none chosen for anyone. They were
not checked against a list of public figures: any resemblance to a real person is chance.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import datetime
import hashlib
import re
from typing import Any, Iterable

SOURCE = "demo-layer"

# The placeholder the corpus generator injects, exactly. Anything else (including "SIM^PATIENT^" with no
# number, or the same text in another case) is not a demo patient.
PLACEHOLDER = re.compile(r"SIM\^PATIENT\^\d+")

FEMALE = ("Anika", "Meera", "Lakshmi", "Farida", "Isha", "Noor", "Tanvi", "Rhea", "Zara", "Helena",
          "Marta", "Ingrid", "Claudia", "Amara", "Leila", "Sofia", "Nadia", "Ayesha", "Petra", "Ananya")
MALE = ("Rohan", "Arjun", "Vikram", "Kabir", "Imran", "Dev", "Nikhil", "Sameer", "Tariq", "Omar",
        "Lucas", "Mateo", "Henrik", "Tomas", "Stefan", "Felix", "Adrian", "Kiran", "Yusuf", "Anton")
SURNAMES = ("Nambiar", "Kulkarni", "Deshpande", "Iyer", "Menon", "Banerjee", "Chatterjee", "Reddy",
            "Naidu", "Patil", "Joshi", "Bhatt", "Sethi", "Chopra", "Dhillon", "Bose", "Pillai", "Varma",
            "Sengupta", "Hegde", "Kamath", "Shetty", "Tiwari", "Saxena", "Mehra", "Ahluwalia", "Rahman",
            "Siddiqui", "Haddad", "Okafor", "Lindqvist", "Novak", "Moreau", "Alvarez", "Brandt",
            "Kowalski", "Fischer", "Castellan", "Ferreira", "Rangan")
SEXES = {"M", "F", "O"}


def _fictional_name(original_id: str, sex: str | None) -> str:
    """Only display_identity() calls this, and only for a placeholder patient."""
    h = int.from_bytes(hashlib.sha256(original_id.encode("utf-8")).digest(), "big")
    firsts = FEMALE if sex == "F" else MALE if sex == "M" else FEMALE + MALE
    return f"{firsts[h % len(firsts)]} {SURNAMES[(h // len(firsts)) % len(SURNAMES)]}"


def _birth_date(value: Any) -> str | None:
    """The identity map's own DICOM date (YYYYMMDD) as an ISO date, or None. Never a made-up one."""
    s = str(value or "").strip()
    if not re.fullmatch(r"\d{8}", s):
        return None
    try:
        return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:])).isoformat()
    except ValueError:
        return None


def display_identity(original_id: str | None, original_name: str | None,
                     dob: str | None = None, sex: str | None = None) -> dict[str, Any] | None:
    """A demo identity for a placeholder patient, else None. Never a name for a record without one."""
    if not original_id or not isinstance(original_name, str) or not PLACEHOLDER.fullmatch(original_name):
        return None
    sex = sex.strip().upper() if isinstance(sex, str) and sex.strip().upper() in SEXES else None
    return {"name": _fictional_name(str(original_id), sex), "dob": _birth_date(dob), "sex": sex,
            "source": SOURCE}


def resolve(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{pseudonym: entry} for identity-map patient rows (pseudo_id, original_id, original_name,
    original_dob, original_sex). A patient with no displayable name is left out, which is not an error."""
    out = {}
    for r in rows:
        entry = display_identity(r.get("original_id"), r.get("original_name"),
                                 r.get("original_dob"), r.get("original_sex"))
        if entry is not None:
            out[r["pseudo_id"]] = entry
    return out
