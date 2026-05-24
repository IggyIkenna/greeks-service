"""Unit tests for instrument_reader.py.

Covers:
- Cache miss → fetches from mock_fetcher
- Cache hit → returns cached value without re-fetching
- Cache expiry → re-fetches after TTL
- Not found → returns None
- force_refresh → bypasses cache
- invalidate → removes entry from cache
- clear_cache → removes all entries
"""

from __future__ import annotations

import time

import pytest

from greeks_service.inputs.instrument_reader import InstrumentReader


class _FakeRecord:
    """Minimal mock instrument record."""

    def __init__(self, key: str) -> None:
        self.instrument_key = key
        self.base_asset = key.split(":")[0] if ":" in key else key


class TestInstrumentReaderCache:
    def _reader(
        self,
        records: dict[str, _FakeRecord | None],
        ttl: int = 300,
    ) -> tuple[InstrumentReader, list[str]]:
        calls: list[str] = []

        def _fetch(key: str) -> object | None:
            calls.append(key)
            return records.get(key)

        reader = InstrumentReader(
            base_url="http://localhost:9999",
            ttl_seconds=ttl,
            mock_fetcher=_fetch,
        )
        return reader, calls

    def test_first_call_fetches_from_fetcher(self) -> None:
        rec = _FakeRecord("ETH:OPTION:ETH-3000-C")
        reader, calls = self._reader({"ETH:OPTION:ETH-3000-C": rec})
        result = reader.get("ETH:OPTION:ETH-3000-C")
        assert result is rec
        assert calls == ["ETH:OPTION:ETH-3000-C"]

    def test_second_call_returns_cache(self) -> None:
        rec = _FakeRecord("ETH:OPTION:ETH-3000-C")
        reader, calls = self._reader({"ETH:OPTION:ETH-3000-C": rec})
        reader.get("ETH:OPTION:ETH-3000-C")
        reader.get("ETH:OPTION:ETH-3000-C")
        assert len(calls) == 1  # fetched only once

    def test_not_found_returns_none(self) -> None:
        reader, _ = self._reader({})
        result = reader.get("UNKNOWN:OPTION:X")
        assert result is None

    def test_force_refresh_bypasses_cache(self) -> None:
        rec = _FakeRecord("BTC:OPTION:BTC-100K-C")
        reader, calls = self._reader({"BTC:OPTION:BTC-100K-C": rec})
        reader.get("BTC:OPTION:BTC-100K-C")
        reader.get("BTC:OPTION:BTC-100K-C", force_refresh=True)
        assert len(calls) == 2

    def test_invalidate_removes_entry(self) -> None:
        rec = _FakeRecord("SOL:OPTION:SOL-200-C")
        reader, calls = self._reader({"SOL:OPTION:SOL-200-C": rec})
        reader.get("SOL:OPTION:SOL-200-C")
        reader.invalidate("SOL:OPTION:SOL-200-C")
        reader.get("SOL:OPTION:SOL-200-C")
        assert len(calls) == 2

    def test_clear_cache_removes_all_entries(self) -> None:
        records = {
            "A": _FakeRecord("A"),
            "B": _FakeRecord("B"),
        }
        reader, calls = self._reader(records)
        reader.get("A")
        reader.get("B")
        reader.clear_cache()
        reader.get("A")
        reader.get("B")
        assert len(calls) == 4  # each fetched twice

    def test_expired_entry_re_fetches(self) -> None:
        rec = _FakeRecord("BTC:SPOT:BTC")
        reader, calls = self._reader({"BTC:SPOT:BTC": rec}, ttl=0)
        reader.get("BTC:SPOT:BTC")
        time.sleep(0.01)  # ensure monotonic time advances
        reader.get("BTC:SPOT:BTC")
        # With ttl=0, every call should fetch since age >= ttl always
        assert len(calls) == 2

    def test_different_keys_cached_independently(self) -> None:
        records = {
            "ETH:OPTION:ETH-3000-C": _FakeRecord("ETH:OPTION:ETH-3000-C"),
            "BTC:OPTION:BTC-100K-C": _FakeRecord("BTC:OPTION:BTC-100K-C"),
        }
        reader, calls = self._reader(records)
        reader.get("ETH:OPTION:ETH-3000-C")
        reader.get("BTC:OPTION:BTC-100K-C")
        reader.get("ETH:OPTION:ETH-3000-C")
        reader.get("BTC:OPTION:BTC-100K-C")
        assert len(calls) == 2  # each key fetched once, cache hit on second
