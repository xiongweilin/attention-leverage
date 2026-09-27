from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


@dataclass(frozen=True)
class SourceTransportPolicy:
    mode: str = 'system'
    min_interval_seconds: float = 0
    max_attempts: int = 2
    backoff_seconds: float = .5

    @classmethod
    def from_config(cls, values: dict | None) -> 'SourceTransportPolicy':
        values = values or {}
        policy = cls(
            mode=values.get('mode', 'system'),
            min_interval_seconds=float(values.get('min_interval_seconds', 0)),
            max_attempts=int(values.get('max_attempts', 2)),
            backoff_seconds=float(values.get('backoff_seconds', .5)),
        )
        if policy.mode not in {'system', 'direct', 'system_then_direct'}:
            raise ValueError(f'unsupported source transport mode: {policy.mode}')
        if policy.min_interval_seconds < 0 or policy.backoff_seconds < 0:
            raise ValueError('source transport delays must be non-negative')
        if policy.max_attempts < 1:
            raise ValueError('source transport max_attempts must be at least 1')
        return policy


class SourceTransport:
    """Per-source request pacing, transient retries, and optional direct routing."""

    def __init__(
        self,
        source: str,
        system_client: httpx.AsyncClient,
        direct_client: httpx.AsyncClient | None = None,
        policy: SourceTransportPolicy | None = None,
    ):
        self.source = source
        self.system_client = system_client
        self.direct_client = direct_client
        self.policy = policy or SourceTransportPolicy()
        self._pace_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self.request('GET', url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self.request('POST', url, **kwargs)

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        routes = self._routes()
        last_error: httpx.TransportError | None = None
        for route_index, client in enumerate(routes):
            for attempt in range(1, self.policy.max_attempts + 1):
                await self._pace()
                try:
                    response = await client.request(method, url, **kwargs)
                except httpx.TransportError as exc:
                    last_error = exc
                    if attempt < self.policy.max_attempts:
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    break

                if response.status_code == 429 or 500 <= response.status_code < 600:
                    if attempt < self.policy.max_attempts:
                        await asyncio.sleep(self._retry_delay(response, attempt))
                        continue
                return response

            # Direct routing is a route fallback for transport failures only.
            if route_index + 1 < len(routes) and last_error is not None:
                continue
            if last_error is not None:
                raise last_error

        raise RuntimeError(f'{self.source} transport did not produce a response')

    def _routes(self) -> list[httpx.AsyncClient]:
        mode = self.policy.mode
        if mode == 'system':
            return [self.system_client]
        if self.direct_client is None:
            raise RuntimeError(f'{self.source} requires a direct HTTP client')
        if mode == 'direct':
            return [self.direct_client]
        return [self.system_client, self.direct_client]

    async def _pace(self) -> None:
        interval = self.policy.min_interval_seconds
        if interval <= 0:
            return
        loop = asyncio.get_running_loop()
        async with self._pace_lock:
            delay = interval - (loop.time() - self._last_request_at)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request_at = loop.time()

    def _backoff(self, attempt: int) -> float:
        return min(self.policy.backoff_seconds * (2 ** (attempt - 1)), 30)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get('Retry-After', '').strip()
        if retry_after:
            try:
                return max(0, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    pass
        return self._backoff(attempt)


def classify_source_error(exc: Exception) -> tuple[str, int | None, str]:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return 'rate_limited', status, f'HTTP {status}'
        if status >= 500:
            return 'server_error', status, f'HTTP {status}'
        return 'http_error', status, f'HTTP {status}'
    if isinstance(exc, httpx.TimeoutException):
        return 'timeout', None, type(exc).__name__
    if isinstance(exc, httpx.ConnectError):
        return 'connect_error', None, type(exc).__name__
    if isinstance(exc, httpx.TransportError):
        return 'transport_error', None, type(exc).__name__
    return 'unexpected', None, type(exc).__name__
