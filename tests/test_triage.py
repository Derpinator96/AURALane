"""Unit tests for the common triage engine stages:
- Calibration
- Signal normalization
- Urgency weighting & Acuity
- Abstention boundaries
- SLA lane assignment
"""
import pytest
import triage
from triage.calibration import calibrate
from triage.signal import signal
from triage.abstention import should_abstain
from triage.lanes import assign_lane


def test_calibration():
    # temperature = 1.6
    # p = 0.5 -> calibrated p ~ 0.500
    c50 = calibrate(0.5, 1.6)
    assert abs(c50 - 0.5) < 0.01

    # High raw probability scaled towards 0.5 by temperature calibration
    c90 = calibrate(0.9, 1.6)
    assert 0.5 < c90 < 0.9


def test_signal_normalization():
    ref = {"mean": 0.10, "sd": 0.05}
    # z = (0.20 - 0.10) / 0.05 = 2.0
    # normalized z in [0.5, 2.5] -> (2.0 - 0.5) / 2.0 = 0.75
    s = signal(0.20, ref, z_floor=0.5, z_ceil=2.5)
    assert abs(s - 0.75) < 0.01


def test_abstention_boundaries():
    # Signal below abstain_lo (0.35) -> no abstention
    assert should_abstain(0.20, abstain_lo=0.35, abstain_hi=0.60) is False

    # Signal in [0.35, 0.60] -> abstention
    assert should_abstain(0.45, abstain_lo=0.35, abstain_hi=0.60) is True

    # Signal above abstain_hi (0.60) -> no abstention
    assert should_abstain(0.75, abstain_lo=0.35, abstain_hi=0.60) is False


def test_lane_assignment():
    # Acuity >= 78 -> CRITICAL (< 15 min)
    lane, sla, sla_min = assign_lane(85.0, abstained=False)
    assert lane == "CRITICAL"
    assert sla_min == 15

    # Acuity 55 -> URGENT (< 1 hr)
    lane, sla, sla_min = assign_lane(55.0, abstained=False)
    assert lane == "URGENT"
    assert sla_min == 60

    # Acuity 30 -> EXPEDITED (< 4 hr)
    lane, sla, sla_min = assign_lane(30.0, abstained=False)
    assert lane == "EXPEDITED"
    assert sla_min == 240

    # Acuity 10 -> ROUTINE (scheduled)
    lane, sla, sla_min = assign_lane(10.0, abstained=False)
    assert lane == "ROUTINE"
    assert sla_min == 1440

    # Abstained -> ABSTAIN lane
    lane, sla, sla_min = assign_lane(70.0, abstained=True)
    assert lane == "ABSTAIN"


def test_cxr_triage_score():
    preds = {"Pneumothorax": 0.85, "Cardiomegaly": 0.10}
    res = triage.score(preds, modality="CXR")

    assert res["driver"] == "Pneumothorax"
    assert res["lane"] == "CRITICAL"
    assert "priority_reason" in res
    assert "Pneumothorax" in res["priority_reason"]
