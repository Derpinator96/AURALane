"""One image preprocessing path, used by every caller.

Previously prepare.py, server.py and the MERN scorer each had their own copy of
these six lines. They agreed, which is lucky rather than designed — and all
three shared two bugs that only show up on the live-upload path, because the
seeded NIH images are all clean 8-bit greyscale:

  RGBA input   img.mean(2) averaged the alpha channel (255 everywhere) into the
               pixel data, brightening the whole image. It did not crash; it
               returned a *different* score. Measured drift: 85.0 -> 83.1 on the
               same radiograph. On a borderline study that flips a lane.

  16-bit input xrv.utils.normalize raises when img.max() exceeds the maxval you
               pass it, and every caller hard-coded 255. A 16-bit PNG — what you
               get exporting from most DICOM viewers — produced HTTP 500 and the
               word "Internal Server Error".

Both matter more for live upload than for the corpus: the corpus is uniform, the
file a jury hands you is not.
"""
import numpy as np
import skimage.io
import torch
import torchxrayvision as xrv

# What "fully bright" means for each dtype we might be handed.
_MAXVAL = {np.dtype("uint8"): 255.0, np.dtype("uint16"): 65535.0}


def read_grayscale(source):
    """path | file-like | bytes -> 2-D float array, plus the maxval it is on."""
    img = skimage.io.imread(source)

    if img.ndim == 3:
        if img.shape[2] == 4:
            img = img[..., :3]          # drop alpha before averaging
        img = img.mean(2)
    elif img.ndim != 2:
        raise ValueError(f"expected a 2-D or 3-D image, got shape {img.shape}")

    maxval = _MAXVAL.get(np.dtype(img.dtype))
    if maxval is None:                  # float, int16, anything else
        top = float(np.nanmax(img))
        maxval = 1.0 if top <= 1.0 else top
    return img, maxval


def to_model_input(source):
    """path | file-like | bytes -> (1, 1, 224, 224) tensor for the DenseNet."""
    img, maxval = read_grayscale(source)
    img = np.clip(img, 0, maxval)       # belt and braces: normalize() raises above maxval
    img = xrv.datasets.normalize(img, maxval)      # -> roughly [-1024, 1024]
    img = img[None, ...]
    img = xrv.datasets.XRayCenterCrop()(img)
    img = xrv.datasets.XRayResizer(224)(img)
    return torch.from_numpy(img)[None, ...]


def predict(model, source):
    """Run the model and return {pathology: raw sigmoid output}."""
    with torch.no_grad():
        out = model(to_model_input(source)).cpu().numpy()[0]
    return {p: float(v) for p, v in zip(model.pathologies, out)}
