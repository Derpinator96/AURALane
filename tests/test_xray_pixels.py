"""Chest X-ray pixels from DICOM: the same picture must score the same however
the scanner stored it (bit depth, MONOCHROME1 or 2).

Before core/xray.py the pipeline handed the model the raw pixel array. imaging.py
takes "fully bright" from the dtype, so a 12-bit image stored in uint16 arrived
near-black and a MONOCHROME1 image arrived as a negative: signals collapsed to 0
or an inverted chest read as Edema at 0.99, and Grad-CAM came back empty.

Uses only the public sample X-ray in shaurya-webapp/tests, written out as
synthetic DICOM here. No test reads images/ or data/.
"""
from pathlib import Path

import numpy as np
import pytest
import torchxrayvision as xrv
from PIL import Image
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from core.pipeline import _model_inputs
from core.xray import chest_pixels

SAMPLE = Path(__file__).resolve().parents[1] / "shaurya-webapp" / "tests" / "16747_3_1.jpg"
VARIANTS = [(8, "MONOCHROME2"), (8, "MONOCHROME1"), (10, "MONOCHROME2"), (12, "MONOCHROME2"),
            (12, "MONOCHROME1"), (14, "MONOCHROME2"), (14, "MONOCHROME1"),
            (16, "MONOCHROME2"), (16, "MONOCHROME1")]


def _picture():
    return np.asarray(Image.open(SAMPLE).convert("L")).astype(np.float64) / 255.0


def make_dicom(bits, photometric, picture=None, signed=False):
    """The one picture as a CR instance the way a scanner with `bits` would write it."""
    picture = _picture() if picture is None else picture
    top = 2 ** bits - 1
    arr = np.rint(picture * top).astype(np.uint8 if bits <= 8 else np.uint16)
    if photometric == "MONOCHROME1":
        arr = (top - arr).astype(arr.dtype)
    if signed:
        arr = arr.astype(np.int16)
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID, ds.SOPInstanceUID = "1.2.840.10008.5.1.4.1.1.1", generate_uid()
    ds.Modality, (ds.Rows, ds.Columns) = "CR", arr.shape
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, photometric
    ds.BitsAllocated = 8 if bits <= 8 else 16
    ds.BitsStored, ds.HighBit = bits, bits - 1
    ds.PixelRepresentation = 1 if signed else 0
    ds.PixelData = arr.tobytes()
    ds.is_little_endian, ds.is_implicit_VR = True, False
    return ds


@pytest.mark.parametrize("bits, photometric", VARIANTS)
def test_pixels_normalise_as_torchxrayvision_reads_a_dicom(bits, photometric):
    """Against xrv.utils.read_xray_dcm's rule, applied by hand: maxval is
    2**BitsStored - 1 and MONOCHROME1 is flipped. The rescale into the container
    costs at most half a level of 65,535, a few hundredths of the 2,048 range."""
    ds = make_dicom(bits, photometric)
    top = 2 ** bits - 1
    raw = ds.pixel_array.astype(np.float64)
    truth = xrv.datasets.normalize(top - raw if photometric == "MONOCHROME1" else raw, top)

    got = chest_pixels(ds)
    full = float(np.iinfo(got.dtype).max)
    ours = xrv.datasets.normalize(got.astype(np.float64), full)
    assert np.abs(ours - truth).max() < 0.05
    assert got.dtype == (np.uint8 if bits <= 8 else np.uint16)


@pytest.mark.parametrize("bits", [8, 16])
def test_a_full_range_image_is_returned_untouched(bits):
    """8-bit and 16-bit studies, which is what the PNG-derived corpus is, score
    exactly as they did before this module existed."""
    ds = make_dicom(bits, "MONOCHROME2")
    assert np.array_equal(chest_pixels(ds), ds.pixel_array)
    assert chest_pixels(ds).dtype == ds.pixel_array.dtype


def test_values_above_bits_stored_are_clipped_not_wrapped():
    ds = make_dicom(12, "MONOCHROME2")
    arr = ds.pixel_array.copy()
    arr[0, :5] = 65535                                   # padding above the 12 stored bits
    ds.PixelData = arr.tobytes()
    assert chest_pixels(ds)[0, :5].tolist() == [65535] * 5
    assert chest_pixels(ds).max() == 65535


def test_signed_pixel_data_is_refused_with_a_reason():
    with pytest.raises(ValueError, match="signed pixel data"):
        chest_pixels(make_dicom(12, "MONOCHROME2", signed=True))


def test_other_photometric_interpretations_pass_through_as_before():
    ds = make_dicom(8, "MONOCHROME2")
    rgb = np.stack([ds.pixel_array] * 3, axis=-1)
    ds.PhotometricInterpretation, ds.SamplesPerPixel, ds.PlanarConfiguration = "RGB", 3, 0
    ds.PixelData = rgb.tobytes()
    assert np.array_equal(chest_pixels(ds), rgb)


def test_the_pipeline_input_builder_uses_it():
    from core.registry import Registry
    entry = Registry().get("cxr-densenet-v1")
    ds = make_dicom(12, "MONOCHROME1")
    got = _model_inputs(entry, None, [ds], None, Path("."))["pixels"]
    assert np.array_equal(got, chest_pixels(ds)) and got.dtype == np.uint16


def test_same_picture_same_findings_however_it_was_stored(tmp_path):
    """End to end through the real model: every storage variant gives the 8-bit
    control's driver, non-empty Grad-CAM, and signals within 0.03. The variants are
    one picture quantised at different depths, so they differ by a little: the
    worst spread measured over all 18 findings and these variants is 0.017."""
    from adapters import multilabel
    from core.providers.local import FileBlob
    from core.providers.local.inference import InProcessInference
    from core.registry import Registry
    from core.types import StudyRef

    entry = Registry().get("cxr-densenet-v1")
    inf = InProcessInference(blob=FileBlob(tmp_path))

    def score(bits, photometric):
        pixels = _model_inputs(entry, None, [make_dicom(bits, photometric)], None, Path("."))["pixels"]
        out = inf.score(StudyRef(f"{bits}-{photometric}", "x"), entry, pixels=pixels)
        return multilabel.adapt(out, {"entry": entry}).findings, out["evidence"]

    control, control_ev = score(8, "MONOCHROME2")
    assert max(control.values()) > 0.5, "the control itself must be a clearly scored picture"
    assert control_ev["gradcam_coverage"] > 0
    for bits, photometric in [(10, "MONOCHROME2"), (12, "MONOCHROME1"), (14, "MONOCHROME2"),
                              (16, "MONOCHROME1")]:
        got, ev = score(bits, photometric)
        assert ev["gradcam_finding"] == control_ev["gradcam_finding"], (bits, photometric)
        assert ev["gradcam_coverage"] > 0, (bits, photometric)
        assert max(abs(got[k] - control[k]) for k in got) < 0.03, (bits, photometric)
