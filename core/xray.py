"""DICOM chest X-ray pixels, in the form imaging.py expects.

imaging.read_grayscale decides what "fully bright" means from the array's dtype:
255 for uint8, 65535 for uint16. That is right for PNGs. A DICOM stores an X-ray
in a 16-bit container but usually uses fewer bits (BitsStored 10, 12 or 14), so a
12-bit image tops out at 4095 and reached the model as a near-black frame, and a
MONOCHROME1 image (0 is white) reached it as a photographic negative. The model
answers a wrong picture confidently: signals collapse to 0, or an inverted chest
reads as Edema at 0.99, and Grad-CAM then explains the wrong picture with an
empty map.

chest_pixels does what torchxrayvision's own DICOM reader does
(xrv.utils.read_xray_dcm, checked in the installed 1.5.4 source):

    maxval   = 2**BitsStored - 1
    MONOCHROME1 -> maxval - data

and then rescales into the container's full range (uint8, or uint16 above 8
bits) so imaging.py's dtype rule lands on the same number. An image already
using its whole container is returned unchanged, so 8-bit and 16-bit PNG-derived
studies score exactly as before.

Not applied, on purpose: RescaleSlope/Intercept and VOI LUTs. read_xray_dcm does
not apply them either, and the model was not trained on windowed pictures.
Anything other than unsigned MONOCHROME1/2 is not guessed at: signed pixel data
is refused with a message, and other photometric interpretations (RGB, YBR) are
passed through untouched, as before this module existed.
"""
from __future__ import annotations

import numpy as np


def chest_pixels(ds) -> np.ndarray:
    arr = ds.pixel_array
    photometric = str(ds.get("PhotometricInterpretation", ""))
    if photometric not in ("MONOCHROME1", "MONOCHROME2"):
        return arr

    if arr.dtype.kind != "u" or int(ds.get("PixelRepresentation", 0)) == 1:
        raise ValueError(
            f"signed pixel data ({arr.dtype}, PixelRepresentation "
            f"{ds.get('PixelRepresentation')}) is not supported for chest X-ray input: "
            f"its brightness range cannot be read from BitsStored without guessing")
    if arr.ndim != 2:
        raise ValueError(f"expected one 2-D frame, got pixel array of shape {arr.shape}")

    stored = int(ds.BitsStored)
    top = 2 ** stored - 1
    container = int(np.iinfo(arr.dtype).max)
    data = np.minimum(arr.astype(np.int64), top)          # anything above BitsStored is padding
    if photometric == "MONOCHROME1":
        data = top - data

    if top == container:
        return data.astype(arr.dtype)                     # already full range: bit-identical
    target = np.uint8 if stored <= 8 else np.uint16
    return np.rint(data * (np.iinfo(target).max / top)).astype(target)
