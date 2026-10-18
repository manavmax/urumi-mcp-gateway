"""The eight WooCommerce tools exposed over MCP (docs/03 §2 contract).

Layer 2 rule: this is the only component that talks to WooCommerce, so every
product/order mutation in the system flows through one of these tools.

Error contract
--------------
`mcp` 1.12 + FastMCP maps *every* exception raised by a tool to a
`CallToolResult` with `isError: true` (see `mcp/server/lowlevel/server.py`
`_make_error_result`), so a JSON-RPC `-32000` response cannot be produced by a tool.
Instead the message is prefixed with a stable machine-readable code that the
gateway can classify:

  WOO_AUTH_FAILED / WOO_NOT_FOUND / WOO_BAD_REQUEST / WOO_UNREACHABLE / WOO_UNEXPECTED

(the gateway maps these to its own audit outcomes; docs/03 §3 is annotated).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Annotated, Literal

from config import get_settings
from image_validate import ImageValidationError, generated_filename, validate_image
from mcp.types import ToolAnnotations
from pydantic import BeforeValidator, Field
from woo_client import (
    _NOT_FOUND_MARKERS,  # reuse the "unknown id" markers
    WooApiError,
    WooRestClient,
    WooUnreachableError,
)

logger = logging.getLogger("woo-mcp.tools")


def blank_to_none(value):
    """Treat a blank optional string as "not provided".

    The MCP Inspector renders a text input for every string-ish parameter and submits
    "" for the ones the user leaves empty, so an unfilled filter must arrive here as
    "" rather than being absent. Every optional parameter below must behave the same
    for both shapes, otherwise `list_orders`/`list_products` fail schema validation
    (Literal / max_length) on a call the user considers empty.
    """

    if isinstance(value, str) and not value.strip():
        return None
    return value


# Optional string/enum parameter that tolerates "" as "not provided". Any pydantic
# constraint is nested INSIDE the union so a blank converts to None before the
# constraint could be applied to a null value.
def blank_optional(inner=str) -> object:
    return Annotated[inner | None, BeforeValidator(blank_to_none)]

PRODUCT_TYPE = Literal["simple", "variable", "grouped", "external"]
PRODUCT_STATUS_FILTER = Literal["publish", "draft", "pending", "private"]
ORDER_STATUS = Literal[
    "pending", "processing", "on-hold", "completed", "cancelled", "refunded", "failed"
]
ORDER_STATUS_FILTER = ORDER_STATUS | Literal["any"]
PER_PAGE = Annotated[int, Field(ge=1, le=100, description="Page size (1-100)")]
PAGE = Annotated[int, Field(ge=1, description="1-based page number")]


def _serialise(payload) -> str:
    """Compact JSON text for the tool's `content` block."""

    return json.dumps(payload, default=str, separators=(",", ":"))


def classify_error(exc: WooApiError) -> tuple[str, str]:
    """Map a WooApiError to (stable code, human message)."""

    body = (exc.message or "").lower()
    if exc.status_code in (401, 403):
        return "WOO_AUTH_FAILED", "Woo auth failed — check Consumer Key"
    if exc.status_code == 404:
        return "WOO_NOT_FOUND", f"{exc.resource.capitalize()} not found in the WooCommerce store"
    if exc.status_code == 400 and any(marker in body for marker in _NOT_FOUND_MARKERS):
        # Woo answers an unknown id with 400 + invalid_id instead of a 404.
        return "WOO_NOT_FOUND", f"{exc.resource.capitalize()} not found in the WooCommerce store"
    if exc.status_code == 400:
        return "WOO_BAD_REQUEST", f"Woo rejected the request (400): {exc.message}"
    return "WOO_API_ERROR", f"Woo {exc.status_code}: {exc.message}"


def register_tools(mcp, client: WooRestClient) -> None:
    """Attach every tool to the FastMCP instance (dependency-injected client)."""

    async def _guard(coro, resource: str = "Resource"):
        """Await a client call, converting failures into prefixed tool errors."""

        try:
            return await coro
        except WooApiError as exc:
            code, message = classify_error(exc)
            raise ValueError(f"{code}: {message}") from exc
        except WooUnreachableError as exc:
            raise ValueError(f"WOO_UNREACHABLE: Woo store unreachable — {exc}") from exc
        except ImageValidationError as exc:
            # F3: upload validation failures are caller-input errors with a stable
            # code (IMAGE_*), distinct from upstream failures.
            raise ValueError(exc.to_tool_error()) from exc
        except ValueError:
            raise
        except Exception as exc:  # defensive: never leak a raw traceback
            logger.exception("unexpected tool failure for %s", resource)
            raise ValueError(f"WOO_UNEXPECTED: {exc}") from exc

    @mcp.tool(
        name="list_products",
        title="List products",
        description=(
            "List WooCommerce products. Supports search, status, SKU and pagination; "
            "returns {products:[{id,name,price,sku,status}],page,per_page}."
        ),
        annotations=ToolAnnotations(
            title="List products", readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    async def list_products(
        search: blank_optional(Annotated[str, Field(description="Free-text search")]) = None,
        status: blank_optional(PRODUCT_STATUS_FILTER) = None,
        sku: blank_optional(Annotated[str, Field(max_length=100)]) = None,
        per_page: PER_PAGE = 10,
        page: PAGE = 1,
    ) -> str:
        params: dict = {"per_page": per_page, "page": page}
        if search:
            params["search"] = search
        if status:
            params["status"] = status
        if sku:
            params["sku"] = sku
        products = await _guard(
            client.get("wp-json/wc/v3/products", params=params), "Product"
        )
        trimmed = [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "price": p.get("price"),
                "regular_price": p.get("regular_price"),
                "sku": p.get("sku"),
                "status": p.get("status"),
                "stock_status": p.get("stock_status"),
            }
            for p in (products or [])
        ]
        return _serialise({"products": trimmed, "count": len(trimmed), "page": page, "per_page": per_page})

    @mcp.tool(
        name="get_product",
        title="Get one product",
        description="Fetch a single WooCommerce product by its numeric id.",
        annotations=ToolAnnotations(
            title="Get product", readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    async def get_product(
        id: Annotated[int, Field(ge=1, description="WooCommerce product id")],
    ) -> str:
        product = await _guard(
            client.get(f"wp-json/wc/v3/products/{int(id)}", resource="Product"), "Product"
        )
        return _serialise(
            {
                "id": product.get("id"),
                "name": product.get("name"),
                "price": product.get("price"),
                "regular_price": product.get("regular_price"),
                "sku": product.get("sku"),
                "status": product.get("status"),
                "stock_status": product.get("stock_status"),
                "description": product.get("description", ""),
                "permalink": product.get("permalink", ""),
            }
        )

    @mcp.tool(
        name="create_product",
        title="Create product",
        description="Create a WooCommerce product and return its id.",
        annotations=ToolAnnotations(
            title="Create product", readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    async def create_product(
        name: Annotated[str, Field(min_length=1, max_length=200)],
        regular_price: Annotated[str, Field(pattern=r"^\d+(\.\d{1,2})?$")],
        description: blank_optional(Annotated[str, Field(description="Long description")]) = None,
        sku: blank_optional(Annotated[str, Field(max_length=100)]) = None,
        type: PRODUCT_TYPE = "simple",
    ) -> str:
        body: dict = {
            "name": name,
            "type": type,
            "regular_price": regular_price,
            "description": description or "",
        }
        if sku:
            body["sku"] = sku
        product = await _guard(
            client.post("wp-json/wc/v3/products", json_body=body, resource="Product"), "Product"
        )
        return _serialise(
            {
                "created": True,
                "id": product.get("id"),
                "name": product.get("name"),
                "price": product.get("price"),
                "sku": product.get("sku"),
                "permalink": product.get("permalink", ""),
            }
        )

    @mcp.tool(
        name="list_orders",
        title="List orders",
        description=(
            "List WooCommerce orders with optional ISO-8601 after/before window, "
            "status filter and pagination."
        ),
        annotations=ToolAnnotations(
            title="List orders", readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    async def list_orders(
        after: blank_optional(Annotated[str, Field(description="ISO-8601 lower bound")]) = None,
        before: blank_optional(Annotated[str, Field(description="ISO-8601 upper bound")]) = None,
        status: blank_optional(ORDER_STATUS_FILTER) = None,
        per_page: PER_PAGE = 10,
        page: PAGE = 1,
    ) -> str:
        params: dict = {"per_page": per_page, "page": page}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        if status:
            params["status"] = status
        orders = await _guard(
            client.get("wp-json/wc/v3/orders", params=params, resource="Order")
        )
        trimmed = [
            {
                "id": o.get("id"),
                "status": o.get("status"),
                "total": o.get("total"),
                "currency": o.get("currency"),
                "date_created": o.get("date_created"),
                "payment_method_title": o.get("payment_method_title"),
                "line_items": [
                    {"name": i.get("name"), "quantity": i.get("quantity")}
                    for i in (o.get("line_items") or [])
                ],
            }
            for o in (orders or [])
        ]
        return _serialise({"orders": trimmed, "count": len(trimmed)})

    @mcp.tool(
        name="get_order",
        title="Get one order",
        description="Fetch a single WooCommerce order by its numeric id.",
        annotations=ToolAnnotations(
            title="Get order", readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    async def get_order(
        id: Annotated[int, Field(ge=1, description="WooCommerce order id")],
    ) -> str:
        order = await _guard(client.get(f"wp-json/wc/v3/orders/{int(id)}", resource="Order"), "Order")
        return _serialise(
            {
                "id": order.get("id"),
                "status": order.get("status"),
                "total": order.get("total"),
                "currency": order.get("currency"),
                "date_created": order.get("date_created"),
                "payment_method_title": order.get("payment_method_title"),
                "line_items": [
                    {"name": i.get("name"), "quantity": i.get("quantity")}
                    for i in (order.get("line_items") or [])
                ],
                "billing": order.get("billing", {}),
            }
        )

    @mcp.tool(
        name="update_order_status",
        title="Update order status",
        description=(
            "Update a WooCommerce order status (pending, processing, on-hold, "
            "completed, cancelled, refunded, failed)."
        ),
        annotations=ToolAnnotations(
            title="Update order status",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        ),
    )
    async def update_order_status(
        id: Annotated[int, Field(ge=1, description="WooCommerce order id")],
        status: ORDER_STATUS,
    ) -> str:
        order = await _guard(
            client.put(
                f"wp-json/wc/v3/orders/{int(id)}",
                json_body={"status": status},
                resource="Order",
            ),
            "Order",
        )
        return _serialise(
            {
                "updated": True,
                "id": order.get("id"),
                "status": order.get("status"),
                "total": order.get("total"),
                "date_modified": order.get("date_modified"),
            }
        )

    @mcp.tool(
        name="list_product_images",
        title="List product images",
        description="List the images attached to one WooCommerce product by its numeric id.",
        annotations=ToolAnnotations(
            title="List product images", readOnlyHint=True, destructiveHint=False, idempotentHint=True
        ),
    )
    async def list_product_images(
        id: Annotated[int, Field(ge=1, description="WooCommerce product id")],
    ) -> str:
        product = await _guard(
            client.get(f"wp-json/wc/v3/products/{int(id)}", resource="Product"), "Product"
        )
        images = [
            {"id": i.get("id"), "src": i.get("src"), "alt": i.get("alt", "")}
            for i in (product.get("images") or [])
        ]
        return _serialise({"product_id": product.get("id"), "images": images, "count": len(images)})

    @mcp.tool(
        name="add_product_image",
        title="Add product image",
        description=(
            "Upload an image (base64, png/jpeg/webp) and attach it to a WooCommerce "
            "product. Returns the new image id and URL. This is a write tool."
        ),
        annotations=ToolAnnotations(
            title="Add product image", readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    async def add_product_image(
        product_id: Annotated[int, Field(ge=1, description="WooCommerce product id")],
        image_base64: Annotated[str, Field(min_length=8, max_length=8_400_000, description="Base64 image bytes (png/jpeg/webp, 5 MB cap)")],
        filename: blank_optional(Annotated[str, Field(description="Advisory label only — the stored name is always generated server-side")]) = None,
    ) -> str:
        settings = get_settings()
        try:
            raw = base64.b64decode(image_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("IMAGE_INVALID_BASE64: image_base64 is not valid base64") from exc
        # Shared validation (magic bytes, caps, Pillow re-encode) — see image_validate.
        try:
            data, mime = validate_image(raw, max_bytes=settings.image_max_bytes)
        except ImageValidationError as exc:
            # F3: upload validation failures are caller-input errors with a stable
            # code (IMAGE_*), distinct from upstream failures.
            raise ValueError(exc.to_tool_error()) from exc
        # The stored filename is generated here AND regenerated by WordPress; the
        # caller's `filename` is never used for storage.
        stored_name = generated_filename(mime)
        upload = await _guard(
            client.post(
                "wp-json/urumi/v1/media",
                json_body={"filename": stored_name, "image_base64": base64.b64encode(data).decode()},
                resource="Media",
            ),
            "Media",
        )
        attachment_id = upload.get("id")
        if not attachment_id:
            raise ValueError("WOO_UNEXPECTED: sideload route returned no attachment id")
        product = await _guard(
            client.put(
                f"wp-json/wc/v3/products/{int(product_id)}",
                json_body={"images": [{"id": int(attachment_id)}]},
                resource="Product",
            ),
            "Product",
        )
        attached = next(
            (i for i in (product.get("images") or []) if int(i.get("id", -1)) == int(attachment_id)),
            None,
        )
        return _serialise(
            {
                "attached": True,
                "product_id": product.get("id"),
                "image_id": int(attachment_id),
                "url": (attached or {}).get("src") or upload.get("url"),
                "mime": mime,
            }
        )

    logger.info("registered 8 woo-mcp tools")
