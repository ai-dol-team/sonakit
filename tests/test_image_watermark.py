from io import BytesIO

import pytest
from PIL import Image, ImageChops

from sonakit.capabilities.image_watermark.models import WatermarkLayout, WatermarkPosition
from sonakit.capabilities.image_watermark.service import (
    WatermarkError,
    WatermarkOptions,
    apply_watermark,
    validate_runtime,
)
from sonakit.core.errors import InvalidImageError, UnsupportedImageFormatError


def image_bytes(
    image_format: str = "PNG",
    *,
    size: tuple[int, int] = (800, 500),
    mode: str = "RGB",
    color=(53, 107, 117),
    **save_options,
) -> bytes:
    image = Image.new(mode, size, color)
    output = BytesIO()
    image.save(output, format=image_format, **save_options)
    return output.getvalue()


@pytest.fixture(scope="module", autouse=True)
def require_runtime() -> None:
    validate_runtime()


@pytest.mark.parametrize(
    ("locale", "value", "script"),
    [
        ("en", "Free Trial", "latin"),
        ("zh", "免费试用", "chinese"),
        ("cs", "Zkušební verze zdarma", "latin"),
        ("de", "Gratis testen", "latin"),
        ("es", "Prueba gratis", "latin"),
        ("fr", "Essai gratuit", "latin"),
        ("it", "Prova gratis", "latin"),
        ("ja", "無料トライアル", "japanese"),
        ("pl", "Darmowa próba", "latin"),
        ("pt", "Teste grátis", "latin"),
        ("ru", "Бесплатная проба", "cyrillic"),
        ("hi-IN", "निःशुल्क परीक्षण", "devanagari"),
        ("te-IN", "ఉచిత ట్రయల్", "telugu"),
        ("ta-IN", "இலவச சோதனை", "tamil"),
    ],
)
def test_renders_target_languages(locale: str, value: str, script: str) -> None:
    result = apply_watermark(image_bytes(), WatermarkOptions(text=value))
    assert result.script == script, locale
    assert result.layout == WatermarkLayout.TILED
    assert result.watermark_count > 1
    assert result.media_type == "image/png"
    with Image.open(BytesIO(result.image_bytes)) as output:
        difference = ImageChops.difference(
            output.convert("RGB"), Image.new("RGB", output.size, (53, 107, 117))
        )
        assert difference.getbbox() is not None


@pytest.mark.parametrize("position", list(WatermarkPosition))
def test_places_watermark_at_each_anchor(position: WatermarkPosition) -> None:
    result = apply_watermark(
        image_bytes(size=(600, 400), color=(0, 0, 0)),
        WatermarkOptions(
            text="Free Trial",
            layout=WatermarkLayout.SINGLE,
            position=position,
            font_size=40,
            letter_spacing=0,
            rotation_degrees=0,
            margin=20,
            opacity=1.0,
            stroke_width=0,
        ),
    )
    with Image.open(BytesIO(result.image_bytes)) as output:
        bbox = ImageChops.difference(
            output.convert("RGB"), Image.new("RGB", output.size, (0, 0, 0))
        ).getbbox()
        assert bbox is not None
        center_x, center_y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        if position.value.endswith("left"):
            assert center_x < 300
        elif position.value.endswith("right"):
            assert center_x > 300
        else:
            assert 200 < center_x < 400
        if position.value.startswith("top"):
            assert center_y < 200
        elif position.value.startswith("bottom"):
            assert center_y > 200
        else:
            assert 120 < center_y < 280


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_preserves_source_format(image_format: str) -> None:
    result = apply_watermark(image_bytes(image_format), WatermarkOptions(text="Free Trial"))
    with Image.open(BytesIO(result.image_bytes)) as output:
        assert output.format == image_format
        assert output.size == (800, 500)


@pytest.mark.parametrize("image_format", ["PNG", "WEBP"])
def test_preserves_transparency(image_format: str) -> None:
    result = apply_watermark(
        image_bytes(image_format, mode="RGBA", color=(20, 40, 60, 0)),
        WatermarkOptions(text="Free Trial", opacity=0.5, stroke_width=0),
    )
    with Image.open(BytesIO(result.image_bytes)) as output:
        rgba = output.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0
        assert rgba.getchannel("A").getextrema()[1] > 0


def test_applies_exif_orientation_and_removes_metadata() -> None:
    exif = Image.Exif()
    exif[274] = 6
    result = apply_watermark(
        image_bytes("JPEG", size=(240, 120), exif=exif), WatermarkOptions(text="Free Trial")
    )
    assert (result.width, result.height) == (120, 240)
    with Image.open(BytesIO(result.image_bytes)) as output:
        assert output.getexif().get(274) is None
        assert not output.info.get("exif")


def test_auto_shrinks_and_rejects_impossible_layout() -> None:
    result = apply_watermark(
        image_bytes(size=(220, 100)),
        WatermarkOptions(
            text="Free Trial Free Trial",
            layout=WatermarkLayout.SINGLE,
            font_size=100,
            margin=8,
            rotation_degrees=0,
        ),
    )
    assert 8 <= result.font_size < 100

    with pytest.raises(WatermarkError, match="does not fit"):
        apply_watermark(
            image_bytes(size=(120, 80)),
            WatermarkOptions(
                text="Free Trial",
                layout=WatermarkLayout.SINGLE,
                offset_x=1,
                rotation_degrees=0,
            ),
        )


def test_default_tile_contract_and_font_weight() -> None:
    regular = apply_watermark(
        image_bytes(),
        WatermarkOptions(text="Dynamic 4729", font_weight=400),
    )
    semibold = apply_watermark(
        image_bytes(),
        WatermarkOptions(text="Dynamic 4729", font_weight=600),
    )

    assert semibold.layout == WatermarkLayout.TILED
    assert semibold.watermark_count > 10
    assert regular.image_bytes != semibold.image_bytes


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("  ", "must not be empty"),
        ("Free\nTrial", "single line"),
        ("Free 😀", "Emoji"),
        ("تجربة مجانية", "unsupported writing system"),
        ("a" * 129, "must not exceed 128"),
    ],
)
def test_rejects_invalid_text(text: str, message: str) -> None:
    with pytest.raises(WatermarkError, match=message):
        apply_watermark(image_bytes(), WatermarkOptions(text=text))


def test_rejects_invalid_image_and_format() -> None:
    with pytest.raises(InvalidImageError):
        apply_watermark(b"not an image", WatermarkOptions(text="Free Trial"))
    with pytest.raises(UnsupportedImageFormatError):
        apply_watermark(image_bytes("GIF"), WatermarkOptions(text="Free Trial"))
