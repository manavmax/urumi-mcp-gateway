"""F3 image tools: validation matrix + add/list product images (ADR-035).

The tests drive the real FastMCP tools over the in-memory MCP transport with a fake
Woo client, so a rejection here is a real tool error the gateway would see. The
gateway keeps a mirror of the validator (src/gateway/uploads/validate.py) with the
same semantics; both suites pin the same matrix.
"""

from __future__ import annotations

import base64
import io
import json
from contextlib import asynccontextmanager

import pytest
from image_validate import ImageValidationError, validate_image
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from PIL import Image
from tools import register_tools


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


class FakeWooClient:
    """Records calls; the media sideload POST answers like the mu-plugin."""

    def __init__(self):
        self.calls: list[tuple] = []

    async def get(self, path, params=None, resource=None):
        self.calls.append(("GET", path, params))
        return {
            "id": 7,
            "name": "P",
            "images": [{"id": 99, "src": "https://store.invalid/urumi-1.png", "alt": "alt text"}],
        }

    async def post(self, path, json_body=None, resource=None):
        self.calls.append(("POST", path, json_body or {}))
        return {"id": 42, "url": "https://store.invalid/urumi-1.png", "mime": "image/png"}

    async def put(self, path, json_body=None, resource=None):
        self.calls.append(("PUT", path, json_body or {}))
        return {
            "id": 7,
            "images": [{"id": json_body["images"][0]["id"], "src": "http://x/urumi-1.png"}],
        }


@asynccontextmanager
async def woo_session():
    client = FakeWooClient()
    mcp = FastMCP("woo-test")
    register_tools(mcp, client)
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        yield session, client


def _text(result) -> str:
    return result.content[0].text if result.content else ""


def _payload(result) -> dict:
    return json.loads(_text(result))


# ---------------------------------------------------------------- validation matrix


def test_validator_accepts_png_jpeg_webp():
    for data, mime in (
        (png_bytes(), "image/png"),
        (jpeg_bytes(), "image/jpeg"),
    ):
        out, m = validate_image(data, max_bytes=1_000_000)
        assert m == mime
        assert Image.open(io.BytesIO(out)).format == ("PNG" if mime == "image/png" else "JPEG")


def test_validator_rejects_wrong_magic_bytes():
    # A GIF renamed .png must be rejected by content, not by name.
    with pytest.raises(ImageValidationError) as exc:
        validate_image(b"GIF89a" + b"0" * 32, max_bytes=1_000_000)
    assert exc.value.code == "UNSUPPORTED_IMAGE_TYPE"


def test_validator_rejects_svg_payload():
    with pytest.raises(ImageValidationError) as exc:
        validate_image(svg_bytes(), max_bytes=1_000_000)
    assert exc.value.code == "UNSUPPORTED_IMAGE_TYPE"
    assert "content" in exc.value.message  # the extension/type claim is irrelevant


def test_validator_rejects_oversize():
    with pytest.raises(ImageValidationError) as exc:
        validate_image(b"\x89PNG\r\n\x1a\n" + b"0" * 64, max_bytes=10)
    assert exc.value.code == "IMAGE_TOO_LARGE"


def test_validator_rejects_dimensions_over_4096():
    big = png_bytes(5000, 10)
    with pytest.raises(ImageValidationError) as exc:
        validate_image(big, max_bytes=1_000_000)
    assert exc.value.code == "IMAGE_TOO_LARGE_DIMENSIONS"


def test_reencode_strips_exif():
    raw = jpeg_bytes_with_exif(8, 8)
    out, mime = validate_image(raw, max_bytes=1_000_000)
    assert mime == "image/jpeg"
    assert not Image.open(io.BytesIO(out)).getexif()


def test_reencode_strips_polyglot_trailing_payload():
    # PNG followed by appended junk: a fresh encode cannot carry it.
    data = png_bytes() + b"URUMI-POLYGLOT-JUNK"
    out, mime = validate_image(data, max_bytes=1_000_000)
    assert mime == "image/png"
    assert not out.endswith(b"URUMI-POLYGLOT-JUNK")


def test_generated_filename_ignores_caller():
    from image_validate import generated_filename

    name = generated_filename("image/png")
    assert name.startswith("urumi-") and name.endswith(".png")


# ---------------------------------------------------------------- tool behaviour


@pytest.mark.asyncio
async def test_add_product_image_uploads_and_attaches():
    async with woo_session() as (session, client):
        result = await session.call_tool(
            "add_product_image",
            {"product_id": 7, "image_base64": base64.b64encode(png_bytes()).decode()},
        )
        assert result.isError is False, result.content
        payload = _payload(result)
        assert payload["attached"] is True
        assert payload["product_id"] == 7
        assert payload["mime"] == "image/png"
        assert payload["image_id"] == 42
        assert payload["url"]
        _method, path, body = client.calls[-2]
        assert path == "wp-json/urumi/v1/media"
        # the stored filename is generated; the caller's label is never used
        assert body["filename"].startswith("urumi-")
        assert body["filename"] != "evil.png"
        assert base64.b64decode(body["image_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
        assert client.calls[-1][0] == "PUT"
        assert client.calls[-1][1] == "wp-json/wc/v3/products/7"


@pytest.mark.asyncio
async def test_add_product_image_rejects_wrong_magic_bytes():
    # A GIF renamed .png must be rejected by content, not by name.
    async with woo_session() as (session, client):
        result = await session.call_tool(
            "add_product_image",
            {"product_id": 7, "image_base64": base64.b64encode(gif_bytes()).decode()},
        )
        assert result.isError is True
        assert "UNSUPPORTED_IMAGE_TYPE" in _text(result)
        assert client.calls == []


@pytest.mark.asyncio
async def test_add_product_image_rejects_svg_payload():
    async with woo_session() as (session, _client):
        result = await session.call_tool(
            "add_product_image",
            {"product_id": 7, "image_base64": base64.b64encode(svg_bytes()).decode()},
        )
        assert result.isError is True
        assert "UNSUPPORTED_IMAGE_TYPE" in _text(result)


@pytest.mark.asyncio
async def test_add_product_image_rejects_oversize(monkeypatch):
    class _S:
        image_max_bytes = 10

    monkeypatch.setattr("tools.get_settings", lambda: _S)
    data = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    async with woo_session() as (session, client):
        result = await session.call_tool(
            "add_product_image",
            {"product_id": 7, "image_base64": base64.b64encode(data).decode()},
        )
        assert result.isError is True
        assert "IMAGE_TOO_LARGE" in _text(result)
        assert client.calls == []


@pytest.mark.asyncio
async def test_add_product_image_rejects_dimensions_over_4096():
    big = png_bytes(5000, 10, (1, 2, 3, 255))
    with pytest.raises(ImageValidationError) as exc:
        validate_image(big, max_bytes=1_000_000)
    assert exc.value.code == "IMAGE_TOO_LARGE_DIMENSIONS"


@pytest.mark.asyncio
async def test_add_product_image_rejects_invalid_base64():
    async with woo_session() as (session, _client):
        result = await session.call_tool(
            "add_product_image",
            {"product_id": 7, "image_base64": "not-base64!!"},
        )
        assert result.isError is True
        assert "IMAGE_INVALID_BASE64" in _text(result)


def test_png_with_trailing_payload_is_cleaned():
    data = png_bytes() + b"URUMI-POLYGLOT-JUNK"
    out, mime = validate_image(data, max_bytes=1_000_000)
    assert mime == "image/png"
    assert not out.endswith(b"URUMI-POLYGLOT-JUNK")
    Image.open(io.BytesIO(out)).verify()


# ---------------------------------------------------------------- tool behaviours


@pytest.mark.asyncio
async def test_list_product_images_returns_trimmed_list():
    async with woo_session() as (session, client):
        result = await session.call_tool("list_product_images", {"id": 7})
        assert result.isError is False, result.content
        payload = _payload(result)
        assert payload == {
            "product_id": 7,
            "images": [{"id": 99, "src": "https://store.invalid/urumi-1.png", "alt": "alt text"}],
            "count": 1,
        }
        assert client.calls[0][1] == "wp-json/wc/v3/products/7"
