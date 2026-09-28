"""Readers and distribution: who reads which study.

A reader is a radiologist account. Its id is the string the auth provider puts
in Principal.email (the email, or the username where there is none), so an
assignment matches the person who signs in. Display names and reading pools
come from models/readers.json, keyed by username; anyone not listed there reads
both pools under their username.

Distribution deals studies in priority order (the worklist's own order:
critical first), each to the eligible reader with the fewest studies so far in
this deal, then the fewest in that lane, then the first selected. With every
reader eligible that is plain round robin, so each gets the same count and a
similar share of critical work. A reader is eligible when the study's reading
pool is one of theirs. A pool nobody selected covers is reported before
anything is sent: studies are never dropped.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
READERS_FILE = ROOT / "models" / "readers.json"
POOLS = ("Chest", "Neuro")


def directory(auth, path: Path = READERS_FILE) -> list[dict[str, Any]]:
    """[{id, username, name, pools}] for every radiologist the auth provider knows."""
    config = json.loads(Path(path).read_text())["readers"] if Path(path).exists() else {}
    listed = getattr(auth, "readers", None)
    out, seen = [], set()
    for username, rid in (listed() if listed else []):
        if rid in seen:
            continue
        seen.add(rid)
        c = config.get(username, {})
        out.append({"id": rid, "username": username, "name": c.get("name", username),
                    "pools": list(c.get("pools", POOLS))})
    return out


def coverage_gaps(pools_needed: Iterable[str], readers: list[dict]) -> list[str]:
    """Pools that none of the selected readers read."""
    covered = {p for r in readers for p in r["pools"]}
    return sorted(set(pools_needed) - covered)


class Dealer:
    """One deal: keeps the counts so studies can be dealt all at once or one
    at a time as they finish (simulated ingest)."""

    def __init__(self, readers: list[dict]):
        if not readers:
            raise ValueError("no readers selected")
        self.readers = readers
        self.total: Counter = Counter()
        self.by_lane: dict[str, Counter] = defaultdict(Counter)

    def pick(self, pool: str, lane: str) -> dict:
        eligible = [(i, r) for i, r in enumerate(self.readers) if pool in r["pools"]]
        if not eligible:
            raise LookupError(f"none of the selected readers reads the {pool} pool")
        _, r = min(eligible, key=lambda ir: (self.total[ir[1]["id"]],
                                            self.by_lane[lane][ir[1]["id"]], ir[0]))
        self.total[r["id"]] += 1
        self.by_lane[lane][r["id"]] += 1
        return r


def deal(rows: list[dict], readers: list[dict]) -> list[tuple[dict, dict]]:
    """rows: dicts with study, pool, lane, already in priority order.
    -> [(row, reader)] in the same order. Raises LookupError, naming the pools,
    before assigning anything if a pool is not covered."""
    gaps = coverage_gaps({r["pool"] for r in rows}, readers)
    if gaps:
        raise LookupError("no selected reader reads the " + ", ".join(gaps) + " pool"
                          + ("s" if len(gaps) > 1 else ""))
    dealer = Dealer(readers)
    return [(row, dealer.pick(row["pool"], row["lane"])) for row in rows]


def assign_row(table, row: dict, reader: dict | None, actor: str, at: str,
               action: str = "assign") -> dict:
    """Write an assignment (or clear it with reader None) and its audit event.
    Returns the updated row."""
    from core.types import AuditEvent
    before = row.get("assigned_to")
    row["assigned_to"] = reader["id"] if reader else None
    row["assigned_name"] = reader["name"] if reader else None
    row["assigned_at"] = at if reader else None
    row["opened_at"] = None if before != row["assigned_to"] else row.get("opened_at")
    table.put_item("worklist", row)
    table.append_audit(AuditEvent(
        actor=actor, action=action, study=row["study"], at=at, outcome="ok", duration_ms=0.0,
        detail={"reader": row["assigned_to"], "reader_name": row["assigned_name"],
                "previous": before, "lane": row.get("lane"), "modality": row.get("modality")}))
    return row
