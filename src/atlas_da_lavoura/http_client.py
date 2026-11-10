"""HTTP client with timeout, retry with exponential backoff and request throttling."""

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 120.0,
        max_retries: int = 5,
        backoff_base: float = 2.0,
        min_interval: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(timeout=timeout, transport=transport)
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._min_interval = min_interval
        self._sleep = sleep
        self._last_request_at: float | None = None

    def get_json(self, url: str) -> Any:
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                error: str = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code not in RETRYABLE_STATUS:
                    response.raise_for_status()
                    return response.json()
                error = f"HTTP {response.status_code}"

            if attempt == self._max_retries:
                raise RuntimeError(f"giving up after {attempt + 1} attempts ({error}): {url}")
            delay = self._backoff_base**attempt
            logger.warning("request failed (%s), retrying in %.0fs: %s", error, delay, url)
            self._sleep(delay)

        raise AssertionError("unreachable")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._min_interval:
                self._sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()
