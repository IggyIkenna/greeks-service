"""instruments-service InstrumentRecord reader for greeks-service.

Fetches InstrumentRecord from instruments-service HTTP API.
Caches results locally with a configurable TTL to avoid per-tick HTTP calls.

Per IS->MTDS contract (codex/04-architecture/instruments-service-as-ssot-for-mtds.md),
greeks-service reads instrument metadata via the canonical IS reader path
— never re-derives strike/expiry/right from venue strings.

Integration tests are marked @pytest.mark.requires_credentials and skipped
by default (credentials needed for real IS endpoint).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 300  # 5 minutes — options recomputed per-minute so 5m is fine


@dataclass
class _CacheEntry:
    record: object  # InstrumentRecord
    fetched_at: float  # time.monotonic()


class InstrumentReader:
    """Cached reader for InstrumentRecord from instruments-service HTTP API.

    Uses httpx for synchronous HTTP calls. In unit tests, pass a mock_fetcher
    to bypass real HTTP calls.

    Args:
        base_url: instruments-service base URL (e.g. http://instruments-service:8080).
        ttl_seconds: Cache TTL in seconds (default 5 min).
        mock_fetcher: Optional callable (instrument_key) -> InstrumentRecord | None
            for unit-test injection. If set, HTTP calls are bypassed entirely.
    """

    def __init__(
        self,
        base_url: str,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        mock_fetcher: object | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl_seconds
        self._mock_fetcher = mock_fetcher
        self._cache: dict[str, _CacheEntry] = {}

    def get(self, instrument_key: str, *, force_refresh: bool = False) -> object | None:
        """Return InstrumentRecord for instrument_key, using cache if fresh.

        Args:
            instrument_key: IS canonical key (VENUE:TYPE:SYMBOL).
            force_refresh: Skip cache and re-fetch from IS.

        Returns:
            InstrumentRecord or None if not found or fetch failed.
        """
        now = time.monotonic()
        entry = self._cache.get(instrument_key)
        if entry is not None and not force_refresh:
            if (now - entry.fetched_at) < self._ttl:
                return entry.record

        record = self._fetch(instrument_key)
        if record is not None:
            self._cache[instrument_key] = _CacheEntry(record=record, fetched_at=now)
        return record

    def _fetch(self, instrument_key: str) -> object | None:
        if self._mock_fetcher is not None:
            fetcher = self._mock_fetcher
            if callable(fetcher):
                return fetcher(instrument_key)  # type: ignore[operator]
            return None

        return self._fetch_http(instrument_key)

    def _fetch_http(self, instrument_key: str) -> object | None:
        """Fetch InstrumentRecord from IS HTTP API (returns None on failure)."""
        try:
            import httpx  # noqa: imports-inside-functions
            from unified_api_contracts.internal.reference.instrument import (  # noqa: imports-inside-functions
                InstrumentRecord,
            )

            url = f"{self._base_url}/api/v1/instruments/{instrument_key}"
            resp = httpx.get(url, timeout=5.0)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return InstrumentRecord.model_validate(resp.json())
        except Exception:
            logger.exception(
                "InstrumentReader: failed to fetch instrument_key=%r from %r",
                instrument_key,
                self._base_url,
            )
            return None

    def invalidate(self, instrument_key: str) -> None:
        """Remove a specific entry from cache (force next get() to re-fetch)."""
        self._cache.pop(instrument_key, None)

    def clear_cache(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()
