"""F3 image upload validation — the gateway side of the shared helper.

The canonical rules live in src/woo-mcp/image_validate.py (which validates bytes
again at the woo tool boundary — callers are never trusted); this mirror enforces
the SAME contract for POST /api/chat/uploads, so a file that is rejected by one
service cannot pass the other:

  - only PNG, JPEG and WEBP, decided by MAGIC BYTES (claimed content type and
    extension are never trusted; SVG and GIF are rejected outright)
  - byte cap (IMAGE_UPLOAD_MAX_BYTES, default 5 MB) and a 4096 px per-side cap
  - decompression-bomb guard: declared pixel count checked before any decode,
    Pillow's DecompressionBomb guard behind it
  - Pillow re-encode strips EXIF/GPS metadata and any polyglot payload
"""

from __future__ import annotations

import io
import time
import uuid

from PIL import Image

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

MAX_PIXELS = 4096 * 4096
MAX_SIDE_PX = 4096


class ImageValidationError(ValueError):
    """Caller-input failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

def http_status_of(exc: ImageValidationError) -> int:
    """413 for size failures, 415 for everything content-related."""

    if exc.code in ("IMAGE_TOO_LARGE", "IMAGE_TOO_LARGE_DIMENSIONS", "IMAGE_DECOMPRESSION_BOMB"):
        return 413
    return 415


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


def validate_image(data: bytes, *, max_bytes: int) -> tuple[bytes, str]:
    """Validate and re-encode one image upload.

    Returns (re_encoded_bytes, mime). Raises ImageValidationError with a stable
    code on any rejection; the re-encode is the metadata boundary (EXIF/GPS and
    polyglot payloads cannot survive a fresh Pillow encode).
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
