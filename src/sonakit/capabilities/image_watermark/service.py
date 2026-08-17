from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from math import ceil
from pathlib import Path
from time import perf_counter

import regex
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont, features

from sonakit.capabilities.image_watermark.models import WatermarkLayout, WatermarkPosition
from sonakit.core.errors import CapabilityError
from sonakit.media.images import decode_image, encode_image, image_processing_semaphore

_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
_FONT_FILES: dict[str, dict[int, str]] = {
    "latin_cyrillic": {
        400: "NotoSans-Regular.ttf",
        600: "NotoSans-SemiBold.ttf",
    },
    "chinese": {
        400: "NotoSansCJKsc-Regular.otf",
        600: "NotoSansCJKsc-Bold.otf",
    },
    "japanese": {
        400: "NotoSansCJKjp-Regular.otf",
        600: "NotoSansCJKjp-Bold.otf",
    },
    "devanagari": {
        400: "NotoSansDevanagari-Regular.ttf",
        600: "NotoSansDevanagari-SemiBold.ttf",
    },
    "telugu": {
        400: "NotoSansTelugu-Regular.ttf",
        600: "NotoSansTelugu-SemiBold.ttf",
    },
    "tamil": {
        400: "NotoSansTamil-Regular.ttf",
        600: "NotoSansTamil-SemiBold.ttf",
    },
}
_JOIN_CONTROLS = {"\u200c", "\u200d"}
_MIN_FONT_SIZE = 8
_MAX_TILE_INSTANCES = 10_000


class WatermarkError(CapabilityError):
    def __init__(self, detail: str) -> None:
        super().__init__("invalid_watermark", detail, 400)


@dataclass(frozen=True, slots=True)
class WatermarkOptions:
    text: str
    layout: WatermarkLayout = WatermarkLayout.TILED
    position: WatermarkPosition = WatermarkPosition.BOTTOM_RIGHT
    font_size: int = 16
    font_weight: int = 600
    letter_spacing: float = 1.1
    color: str = "#FFFFFF"
    opacity: float = 0.5
    margin: int | None = None
    offset_x: int = 0
    offset_y: int = 0
    stroke_color: str = "#000000"
    stroke_width: int = 0
    rotation_degrees: float = -28.0
    tile_width: int = 150
    tile_height: int = 81


@dataclass(frozen=True, slots=True)
class WatermarkResult:
    image_bytes: bytes
    media_type: str
    extension: str
    width: int
    height: int
    font_size: int
    layout: WatermarkLayout
    watermark_count: int
    position: WatermarkPosition
    source_format: str
    script: str
    text_length: int
    duration_ms: float


@dataclass(frozen=True, slots=True)
class _TextLayout:
    patch: Image.Image
    font_size: int
    draw_xy: tuple[int, int]


def validate_runtime() -> None:
    if not features.check_feature("raqm"):
        raise RuntimeError("Pillow RAQM support is required for multilingual watermark rendering")

    filenames = [name for weights in _FONT_FILES.values() for name in weights.values()]
    missing = [name for name in filenames if not (_FONT_DIR / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing watermark font files: {', '.join(sorted(missing))}")
    for font_key, weights in _FONT_FILES.items():
        for weight, filename in weights.items():
            if not _font_codepoints(font_key, weight):
                raise RuntimeError(f"Watermark font has no Unicode cmap: {filename}")


def apply_watermark(image_bytes: bytes, options: WatermarkOptions) -> WatermarkResult:
    started_at = perf_counter()
    _validate_options(options)
    text = _normalize_text(options.text)
    script, font_key = _resolve_font(text)

    with image_processing_semaphore:
        decoded = decode_image(image_bytes)
        if options.layout == WatermarkLayout.TILED:
            rendered, actual_font_size, watermark_count = _render_tiled_watermark(
                decoded.image,
                had_alpha=decoded.had_alpha,
                text=text,
                font_key=font_key,
                options=options,
            )
        else:
            rendered, actual_font_size = _render_single_watermark(
                decoded.image,
                had_alpha=decoded.had_alpha,
                text=text,
                font_key=font_key,
                options=options,
            )
            watermark_count = 1
        encoded = encode_image(rendered, decoded.source_format, quality=90, optimize=True)

    return WatermarkResult(
        image_bytes=encoded,
        media_type=decoded.source_format.media_type,
        extension=decoded.source_format.extension,
        width=rendered.width,
        height=rendered.height,
        font_size=actual_font_size,
        layout=options.layout,
        watermark_count=watermark_count,
        position=options.position,
        source_format=decoded.source_format.value,
        script=script,
        text_length=len(text),
        duration_ms=round((perf_counter() - started_at) * 1000, 3),
    )


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFC", value).strip()
    if not text:
        raise WatermarkError("Watermark text must not be empty.")
    if len(text) > 128:
        raise WatermarkError("Watermark text must not exceed 128 characters.")
    if "\n" in text or "\r" in text:
        raise WatermarkError("Watermark text must be a single line.")
    if not any(
        not char.isspace()
        and char not in _JOIN_CONTROLS
        and not unicodedata.category(char).startswith("M")
        for char in text
    ):
        raise WatermarkError("Watermark text must contain a visible character.")
    for char in text:
        category = unicodedata.category(char)
        if category.startswith("C") and char not in _JOIN_CONTROLS:
            raise WatermarkError("Watermark text contains unsupported control characters.")
        codepoint = ord(char)
        if 0x1F000 <= codepoint <= 0x1FAFF or 0x1F1E6 <= codepoint <= 0x1F1FF:
            raise WatermarkError("Emoji are not supported in watermark text.")
    return text


def _validate_options(options: WatermarkOptions) -> None:
    if not 8 <= options.font_size <= 512:
        raise WatermarkError("font_size must be between 8 and 512.")
    if options.font_weight not in {400, 600}:
        raise WatermarkError("font_weight must be either 400 or 600.")
    if not 0 <= options.letter_spacing <= 20:
        raise WatermarkError("letter_spacing must be between 0 and 20 pixels.")
    if not 0.05 <= options.opacity <= 1.0:
        raise WatermarkError("opacity must be between 0.05 and 1.0.")
    if options.margin is not None and not 0 <= options.margin <= 4096:
        raise WatermarkError("margin must be between 0 and 4096.")
    if not -10000 <= options.offset_x <= 10000 or not -10000 <= options.offset_y <= 10000:
        raise WatermarkError("offset values must be between -10000 and 10000.")
    if not 0 <= options.stroke_width <= 32:
        raise WatermarkError("stroke_width must be between 0 and 32.")
    if not -180 <= options.rotation_degrees <= 180:
        raise WatermarkError("rotation_degrees must be between -180 and 180.")
    if not 32 <= options.tile_width <= 4096:
        raise WatermarkError("tile_width must be between 32 and 4096 pixels.")
    if not 24 <= options.tile_height <= 4096:
        raise WatermarkError("tile_height must be between 24 and 4096 pixels.")
    _parse_hex_color(options.color)
    _parse_hex_color(options.stroke_color)


def _resolve_font(text: str) -> tuple[str, str]:
    scripts: set[str] = set()
    for char in text:
        script = _script_for_codepoint(ord(char), unicodedata.category(char))
        if script:
            scripts.add(script)

    if "japanese" in scripts:
        font_key, display_script = "japanese", "japanese"
    elif "han" in scripts:
        font_key, display_script = "chinese", "chinese"
    elif "devanagari" in scripts:
        font_key, display_script = "devanagari", "devanagari"
    elif "telugu" in scripts:
        font_key, display_script = "telugu", "telugu"
    elif "tamil" in scripts:
        font_key, display_script = "tamil", "tamil"
    else:
        font_key = "latin_cyrillic"
        display_script = "cyrillic" if "cyrillic" in scripts else "latin"

    complex_scripts = scripts & {"devanagari", "telugu", "tamil"}
    if len(complex_scripts) > 1 or (complex_scripts and scripts & {"han", "japanese", "cyrillic"}):
        raise WatermarkError(
            "Watermark text mixes scripts that cannot be rendered by one supported font."
        )

    codepoints = _font_codepoints(font_key, 400)
    if any(
        not char.isspace() and char not in _JOIN_CONTROLS and ord(char) not in codepoints
        for char in text
    ):
        raise WatermarkError("Watermark text contains characters not covered by supported fonts.")
    return display_script, font_key


def _script_for_codepoint(codepoint: int, category: str) -> str | None:
    if (
        0x3040 <= codepoint <= 0x30FF
        or 0x31F0 <= codepoint <= 0x31FF
        or 0xFF66 <= codepoint <= 0xFF9F
    ):
        return "japanese"
    if (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x323AF
    ):
        return "han"
    if 0x0900 <= codepoint <= 0x097F or 0xA8E0 <= codepoint <= 0xA8FF:
        return "devanagari"
    if 0x0C00 <= codepoint <= 0x0C7F:
        return "telugu"
    if 0x0B80 <= codepoint <= 0x0BFF:
        return "tamil"
    if (
        0x0400 <= codepoint <= 0x052F
        or 0x2DE0 <= codepoint <= 0x2DFF
        or 0xA640 <= codepoint <= 0xA69F
    ):
        return "cyrillic"
    if (
        0x0041 <= codepoint <= 0x005A
        or 0x0061 <= codepoint <= 0x007A
        or 0x00C0 <= codepoint <= 0x024F
        or 0x1E00 <= codepoint <= 0x1EFF
    ):
        return "latin"
    if category.startswith("L"):
        raise WatermarkError("Watermark text contains an unsupported writing system.")
    return None


def _render_single_watermark(
    image: Image.Image,
    *,
    had_alpha: bool,
    text: str,
    font_key: str,
    options: WatermarkOptions,
) -> tuple[Image.Image, int]:
    width, height = image.size
    short_edge = min(width, height)
    requested_size = options.font_size
    margin = (
        options.margin
        if options.margin is not None
        else max(8, min(64, round(short_edge * 0.03)))
    )
    if margin * 2 >= width or margin * 2 >= height:
        raise WatermarkError("Watermark margin leaves no drawable image area.")

    layout: _TextLayout | None = None
    for candidate_size in range(requested_size, _MIN_FONT_SIZE - 1, -1):
        patch = _render_text_patch(text, font_key, candidate_size, options)
        text_width, text_height = patch.size
        left, top = _position_bbox(
            position=options.position,
            image_width=width,
            image_height=height,
            margin=margin,
            text_width=text_width,
            text_height=text_height,
            offset_x=options.offset_x,
            offset_y=options.offset_y,
        )
        if (
            left < margin
            or top < margin
            or left + text_width > width - margin
            or top + text_height > height - margin
        ):
            continue
        layout = _TextLayout(patch, candidate_size, (round(left), round(top)))
        break

    if layout is None:
        raise WatermarkError("Watermark text does not fit inside the image.")

    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    overlay.alpha_composite(layout.patch, dest=layout.draw_xy)
    composited = Image.alpha_composite(base, overlay)
    return (composited if had_alpha else composited.convert("RGB")), layout.font_size


def _render_tiled_watermark(
    image: Image.Image,
    *,
    had_alpha: bool,
    text: str,
    font_key: str,
    options: WatermarkOptions,
) -> tuple[Image.Image, int, int]:
    width, height = image.size
    requested_size = options.font_size
    rotated_text: Image.Image | None = None
    actual_font_size = requested_size

    for candidate_size in range(requested_size, _MIN_FONT_SIZE - 1, -1):
        candidate = _render_text_patch(text, font_key, candidate_size, options)
        if (
            candidate.width <= min(width, options.tile_width)
            and candidate.height <= min(height, options.tile_height)
        ):
            rotated_text = candidate
            actual_font_size = candidate_size
            break

    if rotated_text is None:
        raise WatermarkError("Watermark text does not fit inside the image.")

    step_x = options.tile_width
    step_y = options.tile_height

    columns = width // step_x + 3
    rows = height // step_y + 3
    if columns * rows > _MAX_TILE_INSTANCES:
        raise WatermarkError("Watermark tile density exceeds the 10000 instance limit.")

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    phase_x = options.offset_x % step_x
    phase_y = options.offset_y % step_y
    count = 0
    row = 0
    y = phase_y - step_y
    while y < height:
        stagger = step_x // 2 if row % 2 else 0
        x = phase_x - step_x - stagger
        while x < width:
            text_x = x + (step_x - rotated_text.width) // 2
            text_y = y + (step_y - rotated_text.height) // 2
            if _composite_clipped(overlay, rotated_text, text_x, text_y):
                count += 1
            x += step_x
        y += step_y
        row += 1

    if count < 2:
        raise WatermarkError("The tiled watermark layout must contain multiple text instances.")

    composited = Image.alpha_composite(image.convert("RGBA"), overlay)
    return (
        composited if had_alpha else composited.convert("RGB"),
        actual_font_size,
        count,
    )


def _render_text_patch(
    text: str,
    font_key: str,
    font_size: int,
    options: WatermarkOptions,
) -> Image.Image:
    font = _load_font(font_key, font_size, options.font_weight)
    patch = _draw_text_with_tracking(text, font, options)
    return patch.rotate(
        -options.rotation_degrees,
        expand=True,
        resample=Image.Resampling.BICUBIC,
    )


def _draw_text_with_tracking(
    text: str,
    font: ImageFont.FreeTypeFont,
    options: WatermarkOptions,
) -> Image.Image:
    clusters = regex.findall(r"\X", text)
    scratch = ImageDraw.Draw(Image.new("L", (1, 1)))
    stroke_width = options.stroke_width
    padding = stroke_width + 4
    alpha = round(options.opacity * 255)
    fill = (*_parse_hex_color(options.color), alpha)
    stroke_fill = (*_parse_hex_color(options.stroke_color), alpha)

    if options.letter_spacing == 0 or len(clusters) == 1:
        bbox = scratch.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        patch = Image.new(
            "RGBA",
            (
                max(1, bbox[2] - bbox[0] + padding * 2),
                max(1, bbox[3] - bbox[1] + padding * 2),
            ),
            (0, 0, 0, 0),
        )
        ImageDraw.Draw(patch).text(
            (padding - bbox[0], padding - bbox[1]),
            text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        return patch

    boxes = [
        scratch.textbbox((0, 0), cluster, font=font, stroke_width=stroke_width, anchor="ls")
        for cluster in clusters
    ]
    advances = [scratch.textlength(cluster, font=font) for cluster in clusters]
    top = min(box[1] for box in boxes)
    bottom = max(box[3] for box in boxes)
    width = ceil(sum(advances) + options.letter_spacing * (len(clusters) - 1))
    patch = Image.new(
        "RGBA",
        (max(1, width + padding * 2), max(1, bottom - top + padding * 2)),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(patch)
    x = float(padding)
    baseline = padding - top
    for cluster, advance in zip(clusters, advances, strict=True):
        draw.text(
            (x, baseline),
            cluster,
            font=font,
            anchor="ls",
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        x += advance + options.letter_spacing
    return patch


def _composite_clipped(
    destination: Image.Image,
    source: Image.Image,
    x: int,
    y: int,
) -> bool:
    left = max(0, x)
    top = max(0, y)
    right = min(destination.width, x + source.width)
    bottom = min(destination.height, y + source.height)
    if left >= right or top >= bottom:
        return False
    crop = source.crop((left - x, top - y, right - x, bottom - y))
    destination.alpha_composite(crop, dest=(left, top))
    return crop.getchannel("A").getbbox() is not None


def _position_bbox(
    *,
    position: WatermarkPosition,
    image_width: int,
    image_height: int,
    margin: int,
    text_width: int,
    text_height: int,
    offset_x: int,
    offset_y: int,
) -> tuple[float, float]:
    horizontal = (
        position.value.rsplit("_", 1)[-1]
        if position is not WatermarkPosition.CENTER
        else "center"
    )
    if position in {WatermarkPosition.CENTER_LEFT, WatermarkPosition.CENTER_RIGHT}:
        vertical = "center"
    elif position.value.startswith("top_"):
        vertical = "top"
    elif position.value.startswith("bottom_"):
        vertical = "bottom"
    else:
        vertical = "center"

    left = {"left": margin, "right": image_width - margin - text_width}.get(
        horizontal, (image_width - text_width) / 2
    )
    top = {"top": margin, "bottom": image_height - margin - text_height}.get(
        vertical, (image_height - text_height) / 2
    )
    return left + offset_x, top + offset_y


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    if len(value) != 7 or not value.startswith("#"):
        raise WatermarkError("Colors must use #RRGGBB format.")
    try:
        return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))
    except ValueError as exc:
        raise WatermarkError("Colors must use #RRGGBB format.") from exc


@lru_cache(maxsize=sum(len(weights) for weights in _FONT_FILES.values()))
def _font_codepoints(font_key: str, font_weight: int) -> frozenset[int]:
    with TTFont(_FONT_DIR / _FONT_FILES[font_key][font_weight], lazy=True) as font:
        return frozenset(font.getBestCmap() or {})


@lru_cache(maxsize=128)
def _load_font(font_key: str, font_size: int, font_weight: int) -> ImageFont.FreeTypeFont:
    if not features.check_feature("raqm"):
        raise RuntimeError("Pillow RAQM support is required for multilingual watermark rendering")
    return ImageFont.truetype(
        str(_FONT_DIR / _FONT_FILES[font_key][font_weight]),
        size=font_size,
        layout_engine=ImageFont.Layout.RAQM,
    )
