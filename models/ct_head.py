"""Head CT adapter — prototype adapter for acute intracranial hemorrhage triage.

STATUS: PROTOTYPE

This adapter uses pre-scored fixture data with realistic probability
distributions derived from published RSNA ICH detection benchmarks.
It demonstrates the architecture: Head CT findings flow through the
same common triage engine as CXR findings.

A real deployment would use a pretrained ICH classifier (e.g., RSNA
ResNet50/DenseNet) running on SageMaker.
"""
import random
from models.base import ModalityAdapter
from schemas import InferenceResult, Finding

# Realistic baseline distributions for Head CT findings.
# Derived from published RSNA 2019 ICH detection challenge statistics.
CT_FINDINGS = {
    "Intracranial_Hemorrhage": {"mean": 0.12, "sd": 0.18},
    "Midline_Shift":           {"mean": 0.06, "sd": 0.10},
    "Acute_Ischemia":          {"mean": 0.09, "sd": 0.14},
    "Skull_Fracture":          {"mean": 0.04, "sd": 0.08},
    "Mass_Lesion":             {"mean": 0.07, "sd": 0.11},
    "Chronic_Changes":         {"mean": 0.25, "sd": 0.15},
}


class HeadCTAdapter(ModalityAdapter):
    """PROTOTYPE adapter — pre-scored fixture for Head CT."""

    @property
    def modality(self) -> str:
        return "CT"

    @property
    def body_part(self) -> str:
        return "HEAD"

    @property
    def model_name(self) -> str:
        return "ICH-Prototype-v0"

    @property
    def model_version(self) -> str:
        return "fixture-1.0"

    @property
    def status(self) -> str:
        return "PRETRAINED PROTOTYPE"

    def infer(self, source=None, preset: str = None,
              seed: int = None) -> InferenceResult:
        """Generate CT findings from fixture distributions.

        preset : 'critical' | 'urgent' | 'routine' | None (random)
        seed   : optional seed for reproducibility
        """
        rng = random.Random(seed)

        if preset == "critical":
            probs = self._critical_preset(rng)
        elif preset == "urgent":
            probs = self._urgent_preset(rng)
        elif preset == "routine":
            probs = self._routine_preset(rng)
        else:
            probs = self._random_sample(rng)

        findings = [
            Finding(name=name, raw_probability=round(prob, 5))
            for name, prob in probs.items()
        ]

        return InferenceResult(
            study_id="",
            modality=self.modality,
            body_part=self.body_part,
            model_name=self.model_name,
            model_version=self.model_version,
            findings=findings,
            status=self.status,
            inference_ms=0,
        )

    def _random_sample(self, rng) -> dict:
        probs = {}
        for name, dist in CT_FINDINGS.items():
            val = rng.gauss(dist["mean"], dist["sd"])
            probs[name] = max(0.0, min(1.0, val))
        return probs

    def _critical_preset(self, rng) -> dict:
        probs = self._random_sample(rng)
        # Force high ICH probability
        probs["Intracranial_Hemorrhage"] = 0.75 + rng.uniform(0, 0.20)
        probs["Midline_Shift"] = 0.40 + rng.uniform(0, 0.30)
        return probs

    def _urgent_preset(self, rng) -> dict:
        probs = self._random_sample(rng)
        probs["Acute_Ischemia"] = 0.55 + rng.uniform(0, 0.25)
        return probs

    def _routine_preset(self, rng) -> dict:
        probs = self._random_sample(rng)
        # Keep everything low
        for k in probs:
            if k != "Chronic_Changes":
                probs[k] = min(probs[k], 0.15)
        probs["Chronic_Changes"] = 0.20 + rng.uniform(0, 0.15)
        return probs
