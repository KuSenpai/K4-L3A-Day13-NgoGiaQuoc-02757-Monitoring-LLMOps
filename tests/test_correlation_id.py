from __future__ import annotations

import asyncio
import re

import httpx

from app.main import app


def _get(headers: dict[str, str] | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health", headers=headers or {})

    return asyncio.run(send())


def test_generates_correlation_id_when_missing() -> None:
    response = _get()
    assert re.fullmatch(r"req-[0-9a-f]{8}", response.headers["x-request-id"])
    assert float(response.headers["x-response-time-ms"]) >= 0


def test_reuses_valid_incoming_request_id() -> None:
    response = _get({"x-request-id": "req-deadbeef"})
    assert response.headers["x-request-id"] == "req-deadbeef"


def test_replaces_invalid_incoming_request_id() -> None:
    response = _get({"x-request-id": "not-valid"})
    assert response.headers["x-request-id"] != "not-valid"
    assert re.fullmatch(r"req-[0-9a-f]{8}", response.headers["x-request-id"])
