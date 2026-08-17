from io import BytesIO

import pytest
from PIL import Image

from sonakit.core.errors import ImageTooLargeError
from sonakit.media.images import decode_image


def test_maps_pillow_decompression_bomb_to_payload_too_large(monkeypatch) -> None:
    output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    with pytest.raises(ImageTooLargeError, match="dimensions exceed"):
        decode_image(output.getvalue())

