"""Tests for make_dicom.burn_in.

    pytest sim/generator/test_make_dicom.py -v

burn_in used to convert the image to PIL mode "L" before drawing. For 16-bit
input that conversion clamps rather than scales, so every value above 255
saturated and the whole frame came back a uniform 65535 with the text lost in
it. It now draws into a separate mask and composites at native bit depth.
"""
import os
import shutil
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_dicom      # noqa: E402

LINES = ["SIM PATIENT 9999", "SIMID-009999", "DOB 19700101"]


def _frame(maxval):
    """A 1024 x 1024 gradient spanning most of the dtype's range, text-free."""
    h = w = 1024
    y, x = np.mgrid[0:h, 0:w]
    lo, hi = (20, 200) if maxval == 255 else (2000, 32000)
    return (lo + (hi - lo) * (x + y) / (h + w)).astype(
        np.uint8 if maxval == 255 else np.uint16)


def _ocr(arr, maxval):
    import pytesseract
    from PIL import Image
    as8 = (arr.astype(np.float64) / maxval * 255).astype(np.uint8)
    return pytesseract.image_to_string(Image.fromarray(as8)).upper()


@pytest.mark.parametrize("maxval", [255, 65535])
@pytest.mark.skipif(shutil.which("tesseract") is None, reason=(
    "needs Tesseract. NOT VERIFIED: that burned-in text is legible to OCR, i.e. that "
    "the privacy corpus actually contains readable identifiers to mask"))
def test_burn_in_adds_text_and_leaves_the_rest_untouched(maxval):
    frame = _frame(maxval)
    out = make_dicom.burn_in(frame, maxval, LINES)

    assert out.dtype == frame.dtype and out.shape == frame.shape
    assert out is not frame and np.array_equal(frame, _frame(maxval)), "input was modified"

    changed = out != frame
    # the text is present: some pixels changed, every changed pixel is at maxval,
    # and they sit in the top-left band where the three lines are drawn
    assert changed.sum() > 1000, "almost nothing was drawn"
    assert (out[changed] == maxval).all(), "text pixels are not at full intensity"
    size = max(16, frame.shape[0] // 42)
    ys, xs = np.nonzero(changed)
    assert ys.max() < int(size * 0.6 + size * 1.25 * len(LINES) + size), "text outside its band"
    assert xs.max() < frame.shape[1] // 2, "text outside its band"
    # the rest of the frame is unchanged, value for value
    assert np.array_equal(out[~changed], frame[~changed])
    # and the text is legible, not just some bright pixels
    text = _ocr(out, maxval)
    assert "SIMID" in text and "PATIENT" in text, f"OCR could not read the burned text: {text!r}"


def test_16bit_frame_is_not_saturated():
    """The original bug: a 16-bit frame came back uniformly 65535."""
    frame = _frame(65535)
    out = make_dicom.burn_in(frame, 65535, LINES)
    saturated = float((out == 65535).mean())
    assert saturated < 0.05, f"{saturated:.0%} of the frame is at 65535"
