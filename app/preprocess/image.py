"""Image decoding and normalisation before recognition."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def load_image(data: bytes) -> np.ndarray:
    """Decode an uploaded image into an (H, W, 3) uint8 RGB array."""
    with Image.open(io.BytesIO(data)) as img:
        return np.asarray(img.convert("RGB"), dtype=np.uint8)


def preprocess(image: np.ndarray) -> np.ndarray:
    """Normalise an image for the recognition models. Currently a pass-through.

    Planned (next-tasks #4): deskew, denoise, binarise, resolution normalisation.
    """
    return image
