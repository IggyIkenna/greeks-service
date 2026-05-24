"""Unit tests for mark_update_sub.py.

Covers:
- decode_mark_update: happy path with all fields
- decode_mark_update: minimal required fields only (carry rates None)
- decode_mark_update: timezone-naive timestamp treated as UTC
- decode_mark_update: raises on missing required field
- MarkUpdateSubscriber.pull_and_dispatch: dispatches + acks on success
- MarkUpdateSubscriber.pull_and_dispatch: skips ack on callback exception
- MarkUpdateSubscriber.pull_and_dispatch: empty queue returns 0
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from greeks_service.inputs.mark_update_sub import MarkUpdateMessage, MarkUpdateSubscriber, decode_mark_update

# ── Fixtures ──────────────────────────────────────────────────────────────────


_TS = datetime(2024, 12, 15, 12, 0, 0, tzinfo=UTC)


def _make_payload(**overrides: object) -> bytes:
    base: dict[str, object] = {
        "instrument_id": "BINANCE:OPTION:ETH-31DEC24-3000-C",
        "mark_price": "3200.00",
        "implied_volatility": "0.65",
        "timestamp_utc": _TS.isoformat(),
        "venue_id": "BINANCE",
        "asset_group": "cefi",
        "source_event_id": "evt-abc123",
    }
    base.update(overrides)
    return json.dumps(base).encode()


# ── decode_mark_update ─────────────────────────────────────────────────────────


class TestDecodeMarkUpdate:
    def test_full_payload_decodes_correctly(self) -> None:
        data = _make_payload(
            dividend_yield="0.015",
            rebase_rate="0.00045",
            funding_rate="0.0001",
            lending_rate="0.04",
            borrow_rate="0.06",
            staking_apy="0.035",
        )
        msg = decode_mark_update(data)
        assert msg.instrument_id == "BINANCE:OPTION:ETH-31DEC24-3000-C"
        assert msg.mark_price == Decimal("3200.00")
        assert msg.implied_volatility == Decimal("0.65")
        assert msg.timestamp_utc == _TS
        assert msg.venue_id == "BINANCE"
        assert msg.asset_group == "cefi"
        assert msg.dividend_yield == Decimal("0.015")
        assert msg.rebase_rate == Decimal("0.00045")
        assert msg.funding_rate == Decimal("0.0001")
        assert msg.staking_apy == Decimal("0.035")
        assert msg.source_event_id == "evt-abc123"

    def test_carry_rates_absent_decoded_as_none(self) -> None:
        msg = decode_mark_update(_make_payload())
        assert msg.dividend_yield is None
        assert msg.rebase_rate is None
        assert msg.funding_rate is None
        assert msg.staking_apy is None

    def test_timezone_naive_timestamp_gets_utc(self) -> None:
        naive_ts = "2024-12-15T12:00:00"
        data = _make_payload(timestamp_utc=naive_ts)
        msg = decode_mark_update(data)
        assert msg.timestamp_utc.tzinfo is not None
        assert msg.timestamp_utc.tzinfo == UTC

    def test_missing_required_field_raises(self) -> None:
        bad = json.dumps({"mark_price": "100.0"}).encode()
        with pytest.raises(KeyError):
            decode_mark_update(bad)

    def test_source_event_id_absent_defaults_to_empty(self) -> None:
        data = _make_payload()
        payload = json.loads(data)
        del payload["source_event_id"]
        msg = decode_mark_update(json.dumps(payload).encode())
        assert msg.source_event_id == ""

    def test_iv_absent_decodes_as_none(self) -> None:
        payload = json.loads(_make_payload())
        del payload["implied_volatility"]
        msg = decode_mark_update(json.dumps(payload).encode())
        assert msg.implied_volatility is None


# ── MarkUpdateSubscriber ───────────────────────────────────────────────────────


class _FakeBus:
    """Minimal MessageBus stand-in for unit tests."""

    def __init__(self, messages: list[tuple[bytes, str]]) -> None:
        self._queue: list[tuple[bytes, str]] = list(messages)
        self.acked: list[str] = []

    def pull(self, subscription: str, max_messages: int = 10, timeout: float = 5.0) -> list[object]:  # noqa: ARG002
        batch = self._queue[:max_messages]
        self._queue = self._queue[max_messages:]

        class _Msg:
            def __init__(self, data: bytes, ack_id: str) -> None:
                self.data = data
                self.ack_id = ack_id
                self.message_id = ack_id

        return [_Msg(d, a) for d, a in batch]

    def acknowledge(self, subscription: str, ack_ids: list[str]) -> None:  # noqa: ARG002
        self.acked.extend(ack_ids)


class TestMarkUpdateSubscriber:
    def _sub(self, messages: list[tuple[bytes, str]], max_messages: int = 10) -> tuple[MarkUpdateSubscriber, _FakeBus]:
        bus = _FakeBus(messages)
        sub = MarkUpdateSubscriber(bus=bus, subscription="test-sub", max_messages=max_messages)  # type: ignore[arg-type]
        return sub, bus

    def test_dispatches_and_acks_on_success(self) -> None:
        data = _make_payload()
        sub, bus = self._sub([(data, "ack-1")])
        received: list[MarkUpdateMessage] = []
        dispatched = sub.pull_and_dispatch(received.append)
        assert dispatched == 1
        assert len(received) == 1
        assert received[0].instrument_id == "BINANCE:OPTION:ETH-31DEC24-3000-C"
        assert bus.acked == ["ack-1"]

    def test_skips_ack_when_callback_raises(self) -> None:
        sub, bus = self._sub([(_make_payload(), "ack-bad")])

        def _failing(_msg: MarkUpdateMessage) -> None:
            raise RuntimeError("boom")

        dispatched = sub.pull_and_dispatch(_failing)
        assert dispatched == 0
        assert bus.acked == []

    def test_empty_queue_returns_zero(self) -> None:
        sub, bus = self._sub([])
        dispatched = sub.pull_and_dispatch(lambda _: None)
        assert dispatched == 0
        assert bus.acked == []

    def test_partial_success_acks_only_good_messages(self) -> None:
        sub, bus = self._sub(
            [
                (_make_payload(), "ack-good"),
                (b"not-valid-json", "ack-bad"),
            ]
        )
        received: list[MarkUpdateMessage] = []
        dispatched = sub.pull_and_dispatch(received.append)
        assert dispatched == 1
        assert bus.acked == ["ack-good"]
