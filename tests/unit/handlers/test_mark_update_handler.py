"""Unit tests for mark_update_handler.py.

Covers:
- Options instrument: greeks computed + carry rates passthrough
- Non-option (PERP): greeks are None, carry rates (funding_rate) populated
- Equity instrument: greeks None, dividend_yield populated
- LST instrument: greeks None, rebase_rate populated
- None InstrumentRecord: greeks None, LedgerRow still emitted
- Expired option (tte <= 0): greeks None
- Zero / missing IV: greeks None
- event_id derives from source_event_id
- _PRICING_LEDGER_CLIENT_ID used on all rows
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from greeks_service.handlers.mark_update_handler import (
    _PRICING_LEDGER_CLIENT_ID,
    MarkUpdateHandler,
)
from greeks_service.inputs.mark_update_sub import MarkUpdateMessage

# ── Helpers ───────────────────────────────────────────────────────────────────


_NOW = datetime(2024, 12, 15, 12, 0, 0, tzinfo=UTC)
_EXPIRY_FUTURE = _NOW + timedelta(days=30)
_EXPIRY_PAST = _NOW - timedelta(seconds=1)


class _FakeInstrument:
    def __init__(
        self,
        *,
        instrument_type: str = "OPTION",
        strike: str | None = "3000.00",
        expiry: datetime | None = None,
        option_type: str | None = "CALL",
        base_asset: str = "ETH",
        asset_class: str = "option",
    ) -> None:
        self.instrument_type = instrument_type
        self.strike = Decimal(strike) if strike else None
        self.expiry = expiry or _EXPIRY_FUTURE
        self.option_type = option_type
        self.base_asset = base_asset
        self.asset_class = asset_class


def _make_msg(
    instrument_id: str = "BINANCE:OPTION:ETH-31DEC24-3000-C",
    mark_price: str = "3200.00",
    iv: str | None = "0.65",
    asset_group: str = "cefi",
    venue_id: str = "BINANCE",
    source_event_id: str = "evt-abc123",
    dividend_yield: str | None = None,
    rebase_rate: str | None = None,
    funding_rate: str | None = None,
    lending_rate: str | None = None,
    borrow_rate: str | None = None,
    staking_apy: str | None = None,
) -> MarkUpdateMessage:
    return MarkUpdateMessage(
        instrument_id=instrument_id,
        mark_price=Decimal(mark_price),
        implied_volatility=Decimal(iv) if iv else None,
        timestamp_utc=_NOW,
        venue_id=venue_id,
        asset_group=asset_group,
        source_event_id=source_event_id,
        dividend_yield=Decimal(dividend_yield) if dividend_yield else None,
        rebase_rate=Decimal(rebase_rate) if rebase_rate else None,
        funding_rate=Decimal(funding_rate) if funding_rate else None,
        lending_rate=Decimal(lending_rate) if lending_rate else None,
        borrow_rate=Decimal(borrow_rate) if borrow_rate else None,
        staking_apy=Decimal(staking_apy) if staking_apy else None,
    )


def _build_handler(
    instrument: object | None,
) -> tuple[MarkUpdateHandler, MagicMock]:
    from greeks_service.inputs.instrument_reader import InstrumentReader
    from greeks_service.outputs.pricing_ledger_writer import PricingLedgerWriter

    reader = InstrumentReader(
        base_url="http://localhost",
        mock_fetcher=lambda _key: instrument,
    )
    mock_writer = MagicMock(spec=PricingLedgerWriter)
    handler = MarkUpdateHandler(
        instrument_reader=reader,
        pricing_ledger_writer=mock_writer,
    )
    return handler, mock_writer


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestOptionsGreeks:
    def test_vanilla_call_greeks_computed(self) -> None:
        instr = _FakeInstrument(option_type="CALL")
        handler, mock_writer = _build_handler(instr)
        msg = _make_msg()
        row = handler.handle(msg)
        assert row.option_delta is not None
        assert row.gamma is not None
        assert row.theta is not None
        assert row.vega is not None
        assert row.rho is not None
        # Delta for deep ITM call should be between 0 and 1
        assert Decimal(0) < row.option_delta < Decimal(1)

    def test_vanilla_put_greeks_computed(self) -> None:
        instr = _FakeInstrument(option_type="PUT")
        handler, _ = _build_handler(instr)
        msg = _make_msg()
        row = handler.handle(msg)
        assert row.option_delta is not None
        # Put delta should be between -1 and 0
        assert Decimal(-1) < row.option_delta < Decimal(0)

    def test_expired_option_greeks_none(self) -> None:
        instr = _FakeInstrument(expiry=_EXPIRY_PAST)
        handler, _ = _build_handler(instr)
        row = handler.handle(_make_msg())
        assert row.option_delta is None
        assert row.gamma is None

    def test_zero_iv_greeks_none(self) -> None:
        instr = _FakeInstrument()
        handler, _ = _build_handler(instr)
        row = handler.handle(_make_msg(iv="0.0"))
        assert row.option_delta is None

    def test_absent_iv_greeks_none(self) -> None:
        instr = _FakeInstrument()
        handler, _ = _build_handler(instr)
        row = handler.handle(_make_msg(iv=None))
        assert row.option_delta is None


class TestCarryRatesPassthrough:
    def test_funding_rate_populated_on_row(self) -> None:
        handler, _ = _build_handler(None)
        msg = _make_msg(funding_rate="0.0001")
        row = handler.handle(msg)
        assert row.funding_rate == Decimal("0.0001")

    def test_dividend_yield_populated_on_row(self) -> None:
        handler, _ = _build_handler(None)
        msg = _make_msg(dividend_yield="0.015")
        row = handler.handle(msg)
        assert row.dividend_yield == Decimal("0.015")

    def test_rebase_rate_populated_on_row(self) -> None:
        handler, _ = _build_handler(None)
        msg = _make_msg(rebase_rate="0.00045")
        row = handler.handle(msg)
        assert row.rebase_rate == Decimal("0.00045")

    def test_staking_apy_populated_on_row(self) -> None:
        handler, _ = _build_handler(None)
        msg = _make_msg(staking_apy="0.035")
        row = handler.handle(msg)
        assert row.staking_apy == Decimal("0.035")

    def test_none_carry_rates_remain_none(self) -> None:
        handler, _ = _build_handler(None)
        row = handler.handle(_make_msg())
        assert row.funding_rate is None
        assert row.dividend_yield is None
        assert row.rebase_rate is None


class TestNoneInstrument:
    def test_no_instrument_record_greeks_none(self) -> None:
        handler, _ = _build_handler(None)
        row = handler.handle(_make_msg())
        assert row.option_delta is None
        assert row.gamma is None

    def test_no_instrument_record_row_still_emitted(self) -> None:
        handler, mock_writer = _build_handler(None)
        row = handler.handle(_make_msg())
        assert row is not None
        mock_writer.write.assert_called_once()


class TestLedgerRowMetadata:
    def test_event_id_derived_from_source(self) -> None:
        handler, _ = _build_handler(None)
        row = handler.handle(_make_msg(source_event_id="src-xyz"))
        assert row.event_id == "src-xyz.greeks"
        assert row.parent_event_id == "src-xyz"

    def test_empty_source_event_id_generates_uuid(self) -> None:
        handler, _ = _build_handler(None)
        row = handler.handle(_make_msg(source_event_id=""))
        assert row.event_id.startswith("greeks-")
        assert row.parent_event_id is None

    def test_client_id_is_pricing_sentinel(self) -> None:
        handler, _ = _build_handler(None)
        row = handler.handle(_make_msg())
        assert row.client_id == _PRICING_LEDGER_CLIENT_ID

    def test_mark_price_on_row(self) -> None:
        handler, _ = _build_handler(None)
        row = handler.handle(_make_msg(mark_price="3200.50"))
        assert row.price == Decimal("3200.50")

    def test_asset_group_passthrough(self) -> None:
        handler, _ = _build_handler(None)
        row = handler.handle(_make_msg(asset_group="defi"))
        assert row.asset_group == "defi"

    def test_venue_passthrough(self) -> None:
        handler, _ = _build_handler(None)
        row = handler.handle(_make_msg(venue_id="HYPERLIQUID"))
        assert row.venue == "HYPERLIQUID"

    def test_delta_is_zero_for_mark_update(self) -> None:
        handler, _ = _build_handler(None)
        row = handler.handle(_make_msg())
        assert row.delta == Decimal(0)

    def test_writer_called_with_asset_group(self) -> None:
        handler, mock_writer = _build_handler(None)
        handler.handle(_make_msg(asset_group="tradfi"))
        mock_writer.write.assert_called_once()
        call_args = mock_writer.write.call_args
        assert call_args.args[1] == "tradfi"


class TestIvFittingFallback:
    """TradFi coverage notes — IV fitting kernel available; handler path pending schema extension.

    The kernel exposes implied_vol_from_price() for callers with both an observed option
    price and an underlying spot. The handler cannot use this path yet because MarkUpdateMessage
    carries only one price field (mark_price = underlying spot). A separate option_mark_price
    or underlying_spot field is required; see plan Phase 3 CODE P0 (TradFi gap).
    """

    def test_no_iv_with_option_instrument_greeks_none(self) -> None:
        """Without IV in message, greeks are None even for option instruments.
        TradFi IV fitting requires underlying_spot in schema — not yet wired."""
        instr = _FakeInstrument(option_type="CALL", strike="100.00")
        handler, _ = _build_handler(instr)
        row = handler.handle(_make_msg(iv=None))
        assert row.option_delta is None

    def test_no_iv_any_mark_price_greeks_none(self) -> None:
        """No IV and any mark_price → greeks None (IV path not wired in handler)."""
        instr = _FakeInstrument(option_type="CALL", strike="100.00")
        handler, _ = _build_handler(instr)
        row = handler.handle(_make_msg(mark_price="0.001", iv=None))
        assert row.option_delta is None

    def test_iv_provided_takes_priority(self) -> None:
        """If IV is provided directly, use it — greeks computed normally."""
        instr = _FakeInstrument(option_type="CALL", strike="100.00")
        handler, _ = _build_handler(instr)
        row = handler.handle(_make_msg(iv="0.50"))
        assert row.option_delta is not None
