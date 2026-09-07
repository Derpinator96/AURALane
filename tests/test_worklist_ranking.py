"""Tests cross-modality worklist ranking invariants:
1. CRITICAL study must rank above ROUTINE study regardless of modality.
2. FIFO ordering must strictly follow arrival index.
"""
import pytest

RANK = {"CRITICAL": 0, "URGENT": 1, "ABSTAIN": 2, "EXPEDITED": 3, "ROUTINE": 4}


def aura_sort_key(study):
    lane = study.get("override", {}).get("human_lane", study["lane"])
    return (RANK[lane], -study.get("acuity", 0))


def test_cross_modality_ranking_invariant():
    studies = [
        {"id": "S1", "modality": "CXR", "lane": "ROUTINE", "acuity": 15.0, "arrival_index": 0},
        {"id": "S2", "modality": "MRI", "lane": "ROUTINE", "acuity": 10.0, "arrival_index": 1},
        {"id": "S3", "modality": "CXR", "lane": "ROUTINE", "acuity": 12.0, "arrival_index": 2},
        {"id": "S4", "modality": "CT", "lane": "CRITICAL", "acuity": 88.0, "arrival_index": 3},
    ]

    # FIFO order: strictly by arrival index
    fifo_ordered = sorted(studies, key=lambda s: s["arrival_index"])
    assert [s["id"] for s in fifo_ordered] == ["S1", "S2", "S3", "S4"]

    # AURALane order: CRITICAL CT study S4 must rise to #1!
    aura_ordered = sorted(studies, key=aura_sort_key)
    assert aura_ordered[0]["id"] == "S4"
    assert aura_ordered[0]["modality"] == "CT"
    assert aura_ordered[0]["lane"] == "CRITICAL"
