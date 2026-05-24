"""Integration smoke test — MTDS mark_update → greeks-service → PricingLedger row.

Pipeline exercised end-to-end using LocalMessageBus (in-memory Pub/Sub) and a
mocked PricingLedgerWriter (no real GCS calls). The MTDS publisher side is
simulated inline with the exact JSON wire format that mark_update_publisher.py
produces — keeping greeks-service self-contained without a cross-repo import.

CLOUD_PROVIDER=local CLOUD_MOCK_MODE=true per workspace testing convention.

Scenario:
  1. Test harness constructs a mark_update JSON payload (mirrors MTDS wire format)
     and publishes it to a LocalMessageBus.
  2. greeks-service MarkUpdateSubscriber pulls from the same LocalMessageBus.
  3. MarkUpdateHandler computes BSM greeks + builds LedgerRow.
  4. PricingLedger LedgerRow is captured and asserted:
     - option_delta / gamma / theta / vega / rho populated (vanilla call)
     - carry-rate passthrough (funding_rate present)
     - event_type == MARK_UPDATE
     - parent_event_id traceable to MTDS source_event_id
     - client_id == _PRICING_LEDGER_CLIENT_ID sentinel
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("CLOUD_PROVIDER", "local")
os.environ.setdefault("CLOUD_MOCK_MODE", "true")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_payload(
    *,
    instrument_id: str,
    mark_price: str,
    timestamp_utc: datetime,
    venue_id: str = "BINANCE",
    asset_group: str = "cefi",
    source_event_id: str = "smoke-test-run-1",
    implied_volatility: str | None = None,
    funding_rate: str | None = None,
    borrow_rate: str | None = None,
    lending_rate: str | None = None,
    staking_apy: str | None = None,
    dividend_yield: str | None = None,
    rebase_rate: str | None = None,
) -> bytes:
    """Construct MTDS mark_update wire-format JSON bytes (mirrors encode_mark_update)."""
    ts = timestamp_utc if timestamp_utc.tzinfo is not None else timestamp_utc.replace(tzinfo=UTC)
    payload: dict[str, object] = {
        "instrument_id": instrument_id,
        "mark_price": mark_price,
        "timestamp_utc": ts.isoformat(),
        "venue_id": venue_id,
        "asset_group": asset_group,
        "source_event_id": source_event_id,
        "implied_volatility": implied_volatility,
        "funding_rate": funding_rate,
        "borrow_rate": borrow_rate,
        "lending_rate": lending_rate,
        "staking_apy": staking_apy,
        "dividend_yield": dividend_yield,
        "rebase_rate": rebase_rate,
    }
    return json.dumps(payload).encode("utf-8")


# ── Fixtures ──────────────────────────────────────────────────────────────────


class _EthCallInstrument:
    """Minimal InstrumentRecord stub for a vanilla ETH call expiring 2025-01-14."""

    instrument_id: str = "BINANCE:OPTION:ETH-14JAN25-3200-C"
    base_asset: str = "ETH"
    asset_class: str = "option"
    option_type: str = "CALL"
    strike: Decimal = Decimal("3200.00")
    expiry: datetime = datetime(2025, 1, 14, 8, 0, 0, tzinfo=UTC)


_ETH_CALL = _EthCallInstrument()
_MARK_PRICE_DATE = datetime(2024, 12, 15, 12, 0, 0, tzinfo=UTC)


def _build_handler(
    instrument: object | None,
) -> tuple[object, MagicMock]:
    from greeks_service.handlers.mark_update_handler import MarkUpdateHandler
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


@pytest.mark.integration
def test_vanilla_call_full_pipeline() -> None:
    """Full pipeline: publish → subscriber pull → handler → LedgerRow with greeks."""
    from unified_trading_library.cloud_interface import LocalMessageBus

    from greeks_service.handlers.mark_update_handler import _PRICING_LEDGER_CLIENT_ID
    from greeks_service.inputs.mark_update_sub import MarkUpdateSubscriber

    bus = LocalMessageBus()
    topic = "mark-update"

    data = _make_payload(
        instrument_id=_ETH_CALL.instrument_id,
        mark_price="3350.00",
        timestamp_utc=_MARK_PRICE_DATE,
        venue_id="BINANCE",
        asset_group="cefi",
        source_event_id=f"smoke-test-run-1:{_ETH_CALL.instrument_id}:{_MARK_PRICE_DATE.isoformat()}",
        implied_volatility="0.72",
        funding_rate="0.0001",
    )
    bus.publish(topic, data)

    handler, mock_writer = _build_handler(_ETH_CALL)
    emitted: list[object] = []

    def _capture(msg: object) -> None:
        emitted.append(handler.handle(msg))  # type: ignore[arg-type]

    subscriber = MarkUpdateSubscriber(bus=bus, subscription=topic)
    dispatched = subscriber.pull_and_dispatch(_capture)

    assert dispatched == 1, f"Expected 1 dispatched, got {dispatched}"
    assert len(emitted) == 1
    row = emitted[0]

    from unified_api_contracts import EventType

    assert row.event_type == EventType.MARK_UPDATE  # type: ignore[union-attr]

    # Greeks computed for vanilla call
    assert row.option_delta is not None, "option_delta must be set"  # type: ignore[union-attr]
    assert row.gamma is not None  # type: ignore[union-attr]
    assert row.theta is not None  # type: ignore[union-attr]
    assert row.vega is not None  # type: ignore[union-attr]
    assert row.rho is not None  # type: ignore[union-attr]
    assert Decimal(0) < row.option_delta < Decimal(1), f"delta={row.option_delta}"  # type: ignore[operator,union-attr]

    # Carry rate passthrough
    assert row.funding_rate == Decimal("0.0001")  # type: ignore[union-attr]

    # Event lineage traceable to MTDS source_event_id
    source_id = f"smoke-test-run-1:{_ETH_CALL.instrument_id}:{_MARK_PRICE_DATE.isoformat()}"
    assert row.parent_event_id == source_id  # type: ignore[union-attr]
    assert row.event_id.endswith(".greeks")  # type: ignore[union-attr]

    # Client ID sentinel
    assert row.client_id == _PRICING_LEDGER_CLIENT_ID  # type: ignore[union-attr]

    # Mark price preserved
    assert row.price == Decimal("3350.00")  # type: ignore[union-attr]

    # Writer called with correct asset_group
    mock_writer.write.assert_called_once()
    assert mock_writer.write.call_args.args[1] == "cefi"


@pytest.mark.integration
def test_perp_no_greeks_funding_rate_passthrough() -> None:
    """Non-option mark_update: greeks are None, carry rate passes through."""
    from unified_trading_library.cloud_interface import LocalMessageBus

    from greeks_service.inputs.mark_update_sub import MarkUpdateSubscriber

    class _PerpInstrument:
        asset_class = "perp"
        base_asset = "ETH"
        option_type = None
        strike = None
        expiry = None

    bus = LocalMessageBus()
    topic = "mark-update-perp"
    bus.publish(
        topic,
        _make_payload(
            instrument_id="BINANCE:PERP:ETHUSDT",
            mark_price="3200.00",
            timestamp_utc=_MARK_PRICE_DATE,
            funding_rate="0.00015",
        ),
    )

    handler, _ = _build_handler(_PerpInstrument())
    emitted: list[object] = []

    def _capture(msg: object) -> None:
        emitted.append(handler.handle(msg))  # type: ignore[arg-type]

    MarkUpdateSubscriber(bus=bus, subscription=topic).pull_and_dispatch(_capture)

    assert len(emitted) == 1
    row = emitted[0]
    assert row.option_delta is None  # type: ignore[union-attr]
    assert row.gamma is None  # type: ignore[union-attr]
    assert row.funding_rate == Decimal("0.00015")  # type: ignore[union-attr]


@pytest.mark.integration
def test_lst_rebase_rate_passthrough() -> None:
    """LST mark_update: rebase_rate passes through when present in payload."""
    from unified_trading_library.cloud_interface import LocalMessageBus

    from greeks_service.inputs.mark_update_sub import MarkUpdateSubscriber

    class _LstInstrument:
        asset_class = "lst"
        base_asset = "stETH"
        option_type = None
        strike = None
        expiry = None

    bus = LocalMessageBus()
    topic = "mark-update-lst"
    bus.publish(
        topic,
        _make_payload(
            instrument_id="LIDO:LST:stETH",
            mark_price="3800.00",
            timestamp_utc=_MARK_PRICE_DATE,
            venue_id="LIDO",
            asset_group="defi",
            rebase_rate="0.0365",
        ),
    )

    handler, _ = _build_handler(_LstInstrument())
    emitted: list[object] = []

    def _capture(msg: object) -> None:
        emitted.append(handler.handle(msg))  # type: ignore[arg-type]

    MarkUpdateSubscriber(bus=bus, subscription=topic).pull_and_dispatch(_capture)

    assert len(emitted) == 1
    row = emitted[0]
    assert row.rebase_rate == Decimal("0.0365")  # type: ignore[union-attr]
    assert row.option_delta is None  # type: ignore[union-attr]


@pytest.mark.integration
def test_equity_dividend_yield_passthrough() -> None:
    """Equity mark_update: dividend_yield passes through from payload."""
    from unified_trading_library.cloud_interface import LocalMessageBus

    from greeks_service.inputs.mark_update_sub import MarkUpdateSubscriber

    class _EquityInstrument:
        asset_class = "etf"
        base_asset = "SPY"
        option_type = None
        strike = None
        expiry = None

    bus = LocalMessageBus()
    topic = "mark-update-equity"
    bus.publish(
        topic,
        _make_payload(
            instrument_id="NYSE:ETF:SPY",
            mark_price="567.50",
            timestamp_utc=_MARK_PRICE_DATE,
            venue_id="NYSE",
            asset_group="tradfi",
            dividend_yield="0.013",
        ),
    )

    handler, _ = _build_handler(_EquityInstrument())
    emitted: list[object] = []

    def _capture(msg: object) -> None:
        emitted.append(handler.handle(msg))  # type: ignore[arg-type]

    MarkUpdateSubscriber(bus=bus, subscription=topic).pull_and_dispatch(_capture)

    assert len(emitted) == 1
    row = emitted[0]
    assert row.dividend_yield == Decimal("0.013")  # type: ignore[union-attr]
    assert row.option_delta is None  # type: ignore[union-attr]
