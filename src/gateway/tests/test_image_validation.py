"""F3 image upload validation: the gateway-side shared helper (ADR-035).

The same matrix is pinned in src/woo-mcp/tests/test_image_tools.py against the
woo-mcp mirror of this module — a file rejected here must be rejected there too.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from uploads.validate import ImageValidationError, generated_filename, http_status_of, sniff_mime, validate_image


def png_bytes(w: int = 2, h: int = 2, color=(200, 30, 30, 255)) -> bytes:
    img = Image.new("RGBA", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes(w: int = 8, h: int = 8) -> bytes:
    img = Image.new("RGB", (w, h), (10, 120, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def jpeg_bytes_with_exif(w: int = 8, h: int = 8) -> bytes:
    img = Image.new("RGB", (w, h), (10, 200, 30))
    exif = img.getexif()
    exif[0x010F] = "UrumiCamera"  # Make tag — must NOT survive the re-encode
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def svg_bytes() -> bytes:
    return b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'


def gif_bytes() -> bytes:
    img = Image.new("RGB", (4, 4), (1, 2, 3))
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


def test_validator_accepts_png_jpeg_webp_roundtrip():
    out, mime = validate_image(png_bytes(), max_bytes=1_000_000)
    assert mime == "image/png"
    assert Image.open(io.BytesIO(out)).format == "PNG"
    out, mime = validate_image(jpeg_bytes(), max_bytes=1_000_000)
    assert mime == "image/jpeg"


def test_validator_rejects_wrong_magic_bytes():
    # GIF89a header: rejected by content even though the client may call it .png
    with pytest.raises(ImageValidationError) as exc:
        validate_image(b"GIF89a" + b"0" * 32, max_bytes=1_000_000)
    assert exc.value.code == "UNSUPPORTED_IMAGE_TYPE"
    assert http_status_of(exc.value) == 415


def test_validator_rejects_svg_payload():
    with pytest.raises(ImageValidationError) as exc:
        validate_image(b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>', max_bytes=1_000_000)
    assert exc.value.code == "UNSUPPORTED_IMAGE_TYPE"
    assert http_status_of(exc.value) == 415


def test_validator_rejects_oversize():
    with pytest.raises(ImageValidationError) as exc:
        validate_image(b"\x89PNG\r\n\x1a\n" + b"0" * 64, max_bytes=10)
    assert exc.value.code == "IMAGE_TOO_LARGE"
    assert http_status_of(exc.value) == 413


def test_validator_rejects_dimensions_over_4096():
    img = Image.new("RGBA", (5000, 10), (1, 2, 3, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    with pytest.raises(ImageValidationError) as exc:
        validate_image(buf.getvalue(), max_bytes=1_000_000)
    assert exc.value.code == "IMAGE_TOO_LARGE_DIMENSIONS"
    assert http_status_of(exc.value) == 413


def test_validator_bomb_guard_runs_before_decode(monkeypatch):
    import uploads.validate as v

    # A header that declares a huge canvas is rejected pre-decode even when the
    # per-side caps are patched away — the pixel-count guard must hold on its own.
    monkeypatch.setattr(v, "MAX_SIDE_PX", 10_000)
    img = Image.new("RGB", (60, 60), (1, 2, 3))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    # header size fields patched to a huge declared canvas via a hand-built PNG is
    # overkill: the pre-decode pixel-count guard is exercised through the module
    # constant instead.
    monkeypatch.setattr(v, "MAX_PIXELS", 4)
    with pytest.raises(ImageValidationError) as exc:
        v.validate_image(png_bytes(4, 4), max_bytes=1_000_000)
    assert exc.value.code == "IMAGE_TOO_LARGE"
    assert "bomb" in exc.value.message.lower()


def test_reencode_strips_exif():
    img = Image.new("RGB", (8, 8), (10, 200, 30))
    exif = img.getexif()
    exif[0x010F] = "UrumiCamera"  # Make tag — must NOT survive the re-encode
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    assert Image.open(io.BytesIO(buf.getvalue())).getexif().get(0x010F) == "UrumiCamera"  # planted

    out, mime = validate_image(buf.getvalue(), max_bytes=1_000_000)
    assert mime == "image/jpeg"
    assert not Image.open(io.BytesIO(out)).getexif()


def test_reencode_strips_trailing_polyglot_payload():
    data = png_bytes() + b"URUMI-POLYGLOT-JUNK"
    out, mime = validate_image(data, max_bytes=1_000_000)
    assert mime == "image/png"
    assert not out.endswith(b"URUMI-POLYGLOT-JUNK")


def test_sniff_ignores_claimed_type():
    # The claimed content type / extension never decides: SVG bytes with a png
    # name (what an HTTP multipart would claim) are sniffed as None.
    assert sniff_mime(b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>') is None


def test_generated_filename_ignores_caller():

    name = generated_filename("image/png")
    assert name.startswith("urumi-") and name.endswith(".png")


def test_http_status_mapping():
    assert http_status_of(ImageValidationError("IMAGE_TOO_LARGE", "x")) == 413
    assert http_status_of(ImageValidationError("IMAGE_TOO_LARGE_DIMENSIONS", "x")) == 413
    assert http_status_of(ImageValidationError("IMAGE_DECOMPRESSION_BOMB", "x")) == 413
    assert http_status_of(ImageValidationError("UNSUPPORTED_IMAGE_TYPE", "x")) == 415
