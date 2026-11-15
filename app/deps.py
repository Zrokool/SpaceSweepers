"""Shared FastAPI dependencies: the outbound HTTP client and the rate limiter."""

import httpx
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http
