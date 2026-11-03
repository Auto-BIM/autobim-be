import io

import numpy as np
import pytest
from PIL import Image

from app.preprocess.image import load_image


@pytest.mark.parametrize("orientation,turns", [(1, 0), (3, 2), (6, 3), (8, 1)])
def test_exif_jpeg_orientation(orientation, turns):
    pixels = np.zeros((20, 40, 3), dtype=np.uint8)
    pixels[:, :20] = (240, 20, 10)
    pixels[:, 20:] = (10, 30, 240)
    image = Image.fromarray(pixels)
    exif = Image.Exif()
    exif[274] = orientation
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif)
    with Image.open(io.BytesIO(buf.getvalue())) as raw:
        expected = np.rot90(np.asarray(raw.convert("RGB")), turns)
    actual = load_image(buf.getvalue())
    assert actual.shape == expected.shape
    assert actual.dtype == np.uint8
    np.testing.assert_array_equal(actual, expected)
