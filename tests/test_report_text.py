"""The structured report draft (core/report_text.py): sections, grading bands,
modality lines, the impression order and the abstention note."""
from core import report_text as rt

CHEST = {"study": "S1", "model_id": "cxr-densenet-v1", "modality": "CR", "lane": "URGENT",
         "clock": "under 1 hr",
         "findings": {"Pneumothorax": 0.72, "Nodule": 0.50, "Edema": 0.10, "Mass": 0.34},
         "urgency": {"Pneumothorax": 1.0, "Nodule": 0.5, "Edema": 0.85, "Mass": 0.58},
         "triage": {"driver": "Pneumothorax", "signal": 0.72, "acuity": 72.0}}


def test_grading_bands():
    assert rt.grade(0.34) == "no convincing evidence of"
    assert rt.grade(0.35) == "possible" and rt.grade(0.60) == "possible"
    assert rt.grade(0.61) == "findings suggestive of"


def test_chest_report_has_every_section_and_grades_each_finding():
    text = rt.build(CHEST)
    order = [text.index(s) for s in ("EXAMINATION", "TECHNIQUE", "COMPARISON", "FINDINGS",
                                     "IMPRESSION", "TRIAGE NOTE")]
    assert order == sorted(order) and "None available." in text
    assert "Findings suggestive of pneumothorax (signal 0.72)." in text
    assert "Possible nodule (signal 0.50)." in text
    assert "No convincing evidence of mass, edema." in text        # by signal, highest first
    # Impression: weighted order (pneumothorax 0.72, nodule 0.25, edema 0.085), three lines.
    imp = text.split("IMPRESSION\n")[1].split("\n\n")[0].splitlines()
    assert imp[0].startswith("1. Findings suggestive of pneumothorax")
    assert imp[1].startswith("2. Possible nodule") and len(imp) == 3
    assert "Queue lane: Urgent. Reading clock: under 1 hr." in text
    assert "Driving finding: pneumothorax" in text
    assert text.rstrip().endswith("replaces every statement.") and "—" not in text


def test_brain_report_states_volumes_in_ml_and_eccentricity():
    text = rt.build({"study": "S2", "model_id": "brain", "modality": "MR", "lane": "CRITICAL",
                     "clock": "under 15 min",
                     "findings": {"enhancing_tumor": 0.9, "mass_effect": 0.4},
                     "urgency": {"enhancing_tumor": 1.0, "mass_effect": 0.9},
                     "evidence": {"volumes_cm3": {"whole_tumour": 40.2, "tumour_core": 22.0,
                                                  "enhancing": 12.5, "edema": 18.2},
                                  "eccentricity": 0.42},
                     "triage": {"driver": "enhancing_tumor", "signal": 0.9}})
    assert "whole tumour 40.2 mL" in text and "enhancing tumour 12.5 mL" in text
    assert "eccentricity from the midline 0.42" in text
    assert "Findings suggestive of enhancing tumour" in text and "Possible mass effect" in text


def test_ct_report_names_the_dominant_subtype_and_likelihood():
    text = rt.build({"study": "S3", "model_id": "ct", "modality": "CT", "lane": "URGENT",
                     "findings": {"subarachnoid_hemorrhage": 0.28},
                     "urgency": {"subarachnoid_hemorrhage": 0.92},
                     "evidence": {"ct": {"dominant_subtype": "subarachnoid", "raw_score": 0.49,
                                         "n_slices": 53, "top_slice_index": 24,
                                         "subtype_scores": {"subarachnoid": 0.49, "subdural": 0.12}}},
                     "triage": {"driver": "subarachnoid_hemorrhage", "signal": 0.28}})
    assert "Dominant subtype subarachnoid hemorrhage, study likelihood 0.49, on slice 25 of 53." in text
    assert "Other subtypes, aggregated probability: subdural 0.12." in text


def test_abstained_report_says_why_no_lane_was_assigned():
    text = rt.build({"study": "S4", "model_id": "cxr", "modality": "CR", "lane": "ABSTAIN",
                     "findings": {"Nodule": 0.5}, "urgency": {"Nodule": 0.5},
                     "triage": {"abstained": True, "driver": "Nodule", "signal": 0.5,
                                "reason": "signal in the band"}})
    assert "Queue lane: Needs human triage. The system did not assign a lane." in text
    assert "inside the 0.35 to 0.60 band" in text
    placed = rt.build({"study": "S4", "model_id": "cxr", "modality": "CR", "lane": "URGENT",
                       "clock": "under 1 hr", "findings": {"Nodule": 0.5}, "urgency": {"Nodule": 0.5},
                       "human_lane": {"by": "r1", "by_name": "Reader 1", "reason": "spiculated"},
                       "triage": {"abstained": True, "reason": "signal in the band"}})
    assert "Lane set by Reader 1: spiculated." in placed and "The system had abstained" in placed
