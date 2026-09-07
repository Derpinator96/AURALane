"""Brain MRI adapter — experimental adapter for structural lesion triage.

STATUS: EXPERIMENTAL

This adapter uses pre-scored fixture data. It demonstrates that Brain MRI
findings flow through the same common triage engine and produce priority
lanes identical in structure to CXR and CT findings.

A real deployment would use a MONAI SegResNet bundle for volumetric brain
tumor segmentation, with derived triage features.
"""
import random
from models.base import ModalityAdapter
from schemas import InferenceResult, Finding

# Realistic baseline distributions for Brain MRI findings.
MRI_FINDINGS = {
    "Structural_Lesion":   {"mean": 0.10, "sd": 0.16},
    "Mass_Effect":         {"mean": 0.05, "sd": 0.09},
    "Hydrocephalus":       {"mean": 0.07, "sd": 0.11},
    "Perilesional_Edema":  {"mean": 0.08, "sd": 0.12},
    "Normal_Parenchyma":   {"mean": 0.72, "sd": 0.18},
}


class BrainMRIAdapter(ModalityAdapter):
    """EXPERIMENTAL adapter — pre-scored fixture for Brain MRI."""

    @property
    def modality(self) -> str:
        return "MRI"

    @property
    def body_part(self) -> str:
        return "BRAIN"

    @property
    def model_name(self) -> str:
        return "BrainMRI-Fixture-v0"

    @property
    def model_version(self) -> str:
        return "fixture-1.0"

    @property
    def status(self) -> str:
        return "EXPERIMENTAL"

    def infer(self, source=None, preset: str = None,
              seed: int = None) -> InferenceResult:
        """Generate MRI findings from fixture distributions.

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
        for name, dist in MRI_FINDINGS.items():
            val = rng.gauss(dist["mean"], dist["sd"])
            probs[name] = max(0.0, min(1.0, val))
        return probs

    def _critical_preset(self, rng) -> dict:
        probs = self._random_sample(rng)
        probs["Mass_Effect"] = 0.70 + rng.uniform(0, 0.25)
        probs["Structural_Lesion"] = 0.65 + rng.uniform(0, 0.25)
        probs["Normal_Parenchyma"] = 0.05 + rng.uniform(0, 0.10)
        return probs

    def _urgent_preset(self, rng) -> dict:
        probs = self._random_sample(rng)
        probs["Hydrocephalus"] = 0.55 + rng.uniform(0, 0.25)
        probs["Structural_Lesion"] = 0.45 + rng.uniform(0, 0.25)
        probs["Normal_Parenchyma"] = 0.10 + rng.uniform(0, 0.15)
        return probs

    def _routine_preset(self, rng) -> dict:
        probs = self._random_sample(rng)
        for k in probs:
            if k != "Normal_Parenchyma":
                probs[k] = min(probs[k], 0.12)
        probs["Normal_Parenchyma"] = 0.75 + rng.uniform(0, 0.20)
        return probs
