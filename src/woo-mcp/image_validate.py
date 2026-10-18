"""Upload validation shared by every image path in woo-mcp (F3, ADR-035).

Contract (docs/DECISIONS.md ADR-035, STEP 3):
  - only PNG, JPEG and WEBP are accepted, decided by MAGIC BYTES: the claimed
    content type and file extension are never trusted (SVG, GIF, HTML, PDF...
    all fail here, whatever they call themselves)
  - size cap (IMAGE_UPLOAD_MAX_BYTES, default 5 MB) and a 4096 px per-side cap
  - decompression-bomb guard: the declared pixel count is checked BEFORE any
    full decode, and Pillow's own DecompressionBomb guard backs this up
  - the image is re-encoded with Pillow: a fresh encode drops EXIF/GPS metadata
    and any polyglot payload appended after the real image data
  - the stored filename is GENERATED here; the caller's filename is never used

The gateway keeps a mirror of this module (src/gateway/uploads/validate.py) for
its own upload endpoint: the two services are separate containers, so the test
matrix (tests/test_image_tools.py) pins identical semantics in both.
"""

from __future__ import annotations

import io
import time
import uuid

from PIL import Image

# The only accepted formats. Everything else — including SVG (polyglot text/JS)
# and GIF (decompression-friendly frames) — is rejected before any decode.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

# Hard pixel-count ceiling independent of the per-side cap (4096x4096): a header
# that declares more than this never reaches the decoder.
MAX_PIXELS = 4096 * 4096
MAX_SIDE_PX = 4096


class ImageValidationError(ValueError):
    """Caller-input failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_tool_error(self) -> str:
        return f"{self.code}: {self.message}"


def sniff_mime(data: bytes) -> str | None:
    """MIME by magic bytes only — the claimed type/extension is never trusted."""

    if data.startswith(PNG_MAGIC):
        return "image/png"
    if data.startswith(JPEG_MAGIC):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def generated_filename(mime: str) -> str:
    """Server-generated stored name; the caller's filename is never used."""

    ext = EXTENSIONS.get(mime, "bin")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"urumi-{stamp}-{uuid.uuid4().hex[:8]}.{ext}"


def _is_webp(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def validate_image(data: bytes, *, max_bytes: int) -> tuple[bytes, str]:
    """Validate and re-encode one image upload.

    Returns (re_encoded_bytes, mime). Raises ImageValidationError with a stable
    code on any rejection. The re-encode is the metadata boundary: EXIF/GPS and
    trailing polyglot bytes cannot survive a fresh Pillow encode.
    """

    if not data:
        raise ImageValidationError("EMPTY_IMAGE", "the uploaded file is empty")
    if len(data) > max_bytes:
        raise ImageValidationError(
            "IMAGE_TOO_LARGE", f"image exceeds the {max_bytes // (1024 * 1024)} MB cap ({len(data)} bytes)"
        )
    mime = sniff_mime(data)
    if mime is None:
        raise ImageValidationError(
            "UNSUPPORTED_IMAGE_TYPE",
            "only png, jpeg and webp images are accepted (checked by content, not extension)",
        )

    try:
        img = Image.open(io.BytesIO(data))
        # Pillow is lazy: open() reads only the header, so these checks run
        # BEFORE any pixel decode and cannot be turned into a CPU bomb by a
        # lying header. Pillow's DecompressionBomb guard still protects the
        # decode itself (raises on load for >MAX_IMAGE_PIXELS*2).
        width, height = img.size
        if width > MAX_SIDE_PX or height > MAX_SIDE_PX:
            raise ImageValidationError(
                "IMAGE_TOO_LARGE_DIMENSIONS", f"image exceeds the {MAX_SIDE_PX} px per-side cap"
            )
        if width * height > MAX_PIXELS:
            raise ImageValidationError(
                "IMAGE_TOO_LARGE", "image pixel count exceeds the decompression-bomb cap"
            )
        img.load()  # force decode: a lying header or truncated bomb fails here
    except Image.DecompressionBombError as exc:
        raise ImageValidationError(
            "IMAGE_DECOMPRESSION_BOMB", "image exceeds the safe pixel budget"
        ) from exc
    except Image.UnidentifiedImageError as exc:
        raise ImageValidationError(
            "UNSUPPORTED_IMAGE_TYPE", "only png, jpeg and webp images are accepted"
        ) from exc
    except ImageValidationError:
        raise
    except Exception as exc:
        raise ImageValidationError(
            "IMAGE_DECODE_FAILED", f"image could not be decoded: {exc.__class__.__name__}"
        ) from exc

    # Re-encode: a fresh encode carries no EXIF/GPS (Pillow only re-emits what it
    # is explicitly handed) and no bytes appended after the image data.
    fmt = img.format
    if fmt not in ("PNG", "JPEG", "WEBP"):
        raise ImageValidationError(
            "UNSUPPORTED_IMAGE_TYPE", "only png, jpeg and webp images are accepted"
        )
    out = io.BytesIO()
    try:
        if fmt == "JPEG":
            img.convert("RGB").save(out, format="JPEG")
        else:
            img.save(out, format=fmt)
    except Exception as exc:
        raise ImageValidationError(
            "IMAGE_ENCODE_FAILED", "image could not be re-encoded safely"
        ) from exc
    encoded = out.getvalue()
    if not encoded or sniff_mime(encoded) != mime:
        raise ImageValidationError(
            "IMAGE_ENCODE_FAILED", "re-encoded image failed the format check"
        )
    return encoded, mime
