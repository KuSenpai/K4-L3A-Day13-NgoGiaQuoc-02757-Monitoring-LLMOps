from __future__ import annotations

import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

CORRELATION_ID_PATTERN = re.compile(r"req-[0-9a-f]{8}")

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Xóa context của request trước để không rò correlation_id/metadata giữa các request
        clear_contextvars()

        # Nhận x-request-id hợp lệ từ client, nếu không có/sai format thì sinh req-<8-hex>
        incoming = request.headers.get("x-request-id", "").strip()
        if CORRELATION_ID_PATTERN.fullmatch(incoming):
            correlation_id = incoming
        else:
            correlation_id = f"req-{uuid.uuid4().hex[:8]}"

        bind_contextvars(correlation_id=correlation_id)
        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        response.headers["x-request-id"] = correlation_id
        response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"
        return response
