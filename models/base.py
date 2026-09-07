"""Abstract base class for modality-specific AI adapters.

Every modality — CXR, CT, MRI — implements this interface so the rest of the
platform never touches model-specific code. The adapter takes raw image data
and returns a normalised InferenceResult that the common triage engine can
consume.
"""
from abc import ABC, abstractmethod
from schemas import InferenceResult


class ModalityAdapter(ABC):
    """Contract every modality adapter must satisfy."""

    @property
    @abstractmethod
    def modality(self) -> str:
        """Return the modality code: 'CXR', 'CT', or 'MRI'."""

    @property
    @abstractmethod
    def body_part(self) -> str:
        """Return the body part: 'CHEST', 'HEAD', or 'BRAIN'."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable model identifier."""

    @property
    @abstractmethod
    def model_version(self) -> str:
        """Weight version or semantic version string."""

    @property
    @abstractmethod
    def status(self) -> str:
        """'LIVE', 'PROTOTYPE', or 'EXPERIMENTAL'."""

    @abstractmethod
    def infer(self, source) -> InferenceResult:
        """Run inference on the given source and return normalised findings.

        source : file path, file-like object, or bytes — whatever the
                 modality-specific preprocessor can handle.
        """

    def warm(self) -> float:
        """Optional: pre-load model weights. Returns seconds taken."""
        return 0.0
