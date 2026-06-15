"""mark_update orchestrator for greeks-service.

Receives MarkUpdateMessage events from the MTDS mark_update subscriber,
reads InstrumentRecord from IS, computes option greeks via BlackScholesKernel,
and emits PricingLedger LedgerRow (event_type=MARK_UPDATE) with both greek
and carry-family columns populated.

None-handling discipline:
- Greeks (option_delta/gamma/theta/vega/rho): None for non-option instruments.
- Carry rates: None for non-applicable instruments (per Phase 1/2 convention).
  Never emit synthetic zero in place of None.

Per codex/04-architecture/client-funds-isolation.md: PricingLedger rows use
the _PRICING_LEDGER_CLIENT_ID sentinel — PricingLedger is client-agnostic.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from unified_api_contracts import (
    EventOrigin,
    EventType,
    LedgerRow,
)
from unified_api_contracts import (
    LedgerAssetClass as AssetClass,
)

from greeks_service.inputs.instrument_reader import InstrumentReader
from greeks_service.inputs.mark_update_sub import MarkUpdateMessage
from greeks_service.kernels.black_scholes import BlackScholesKernel, GreekResult
from greeks_service.outputs.pricing_ledger_writer import PricingLedgerWriter

logger = logging.getLogger(__name__)

# PricingLedger rows are client-agnostic — sentinel per greeks-service codex overview
_PRICING_LEDGER_CLIENT_ID = "_pricing"
_PRICING_LEDGER_ACCOUNT_ID = "_pricing_ledger"
_RISK_FREE_RATE = Decimal("0.05")  # 5% — operator-tunable via config in Phase 3.1


class MarkUpdateHandler:
    """Orchestrates greeks computation and PricingLedger row emission.

    Args:
        instrument_reader: IS reader for InstrumentRecord lookup.
        pricing_ledger_writer: Writer for PricingLedger GCS output.
        kernel: BlackScholesKernel (or any GreekKernel protocol impl).
        risk_free_rate: Continuously-compounded risk-free rate (annualised).
    """

    def __init__(
        self,
        instrument_reader: InstrumentReader,
        pricing_ledger_writer: PricingLedgerWriter,
        kernel: BlackScholesKernel | None = None,
        risk_free_rate: Decimal = _RISK_FREE_RATE,
    ) -> None:
        self._reader = instrument_reader
        self._writer = pricing_ledger_writer
        self._kernel = kernel or BlackScholesKernel()
        self._risk_free_rate = risk_free_rate

    def handle(self, msg: MarkUpdateMessage) -> None:
        """Process one mark_update event: compute greeks + emit PricingLedger row.

        Args:
            msg: Decoded MTDS mark_update event.
        """
        instrument = self._reader.get(msg.instrument_id)
        greek_result = self._compute_greeks(msg, instrument)
        row = self._build_ledger_row(msg, instrument, greek_result)
        self._writer.write([row], msg.asset_group)

    def _compute_greeks(
        self,
        msg: MarkUpdateMessage,
        instrument: object | None,
    ) -> GreekResult | None:
        """Compute greeks if instrument is an option with sufficient data.

        IV resolution: msg.implied_volatility (CeFi, e.g. Deribit) or None.
        TradFi IV fitting requires underlying_spot in schema — not yet wired.
        """
        inputs = _resolve_option_inputs(msg, instrument)
        if inputs is None:
            return None
        strike, time_to_expiry, right, iv, dividend_yield = inputs
        try:
            return self._kernel.compute(
                spot=msg.mark_price,
                strike=strike,
                time_to_expiry=time_to_expiry,
                risk_free_rate=self._risk_free_rate,
                volatility=iv,
                right=right,
                dividend_yield=dividend_yield,
            )
        except Exception:
            logger.exception(
                "MarkUpdateHandler: greeks compute failed for instrument_id=%r",
                msg.instrument_id,
            )
            return None

    def _build_ledger_row(
        self,
        msg: MarkUpdateMessage,
        instrument: object | None,
        greek_result: GreekResult | None,
    ) -> LedgerRow:
        """Construct the PricingLedger LedgerRow for this mark_update event."""
        event_id = _make_event_id(msg.source_event_id)
        asset_class = _resolve_asset_class(instrument)
        option_delta, gamma, theta, vega, rho = _unpack_greeks(greek_result)

        ts = msg.timestamp_utc
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        return LedgerRow(
            event_id=event_id,
            row_id=f"{event_id}.0",
            event_origin=EventOrigin.PASSIVE,
            event_type=EventType.MARK_UPDATE,
            parent_event_id=msg.source_event_id if msg.source_event_id else None,
            timestamp_utc=ts,
            asset_group=msg.asset_group,
            venue=msg.venue_id,
            account_id=_PRICING_LEDGER_ACCOUNT_ID,
            client_id=_PRICING_LEDGER_CLIENT_ID,
            asset_symbol=_get_str_attr(instrument, "base_asset") or msg.instrument_id,
            asset_canonical_id=msg.instrument_id,
            asset_class=asset_class,
            delta=Decimal(0),
            price=msg.mark_price,
            option_delta=option_delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            rho=rho,
            funding_rate=msg.funding_rate,
            lending_rate=msg.lending_rate,
            borrow_rate=msg.borrow_rate,
            staking_apy=msg.staking_apy,
            dividend_yield=msg.dividend_yield,
            rebase_rate=msg.rebase_rate,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

_SECONDS_PER_YEAR = 365.25 * 24 * 3600


def _resolve_option_inputs(
    msg: MarkUpdateMessage,
    instrument: object | None,
) -> tuple[Decimal, Decimal, str, Decimal, Decimal] | None:
    """Extract and validate option params needed for kernel.compute().

    Returns (strike, time_to_expiry, right, iv, dividend_yield) or None.
    None when instrument is absent, not an option, expired, or IV is absent/zero.
    """
    if instrument is None:
        return None
    strike = _get_decimal_attr(instrument, "strike")
    expiry = _get_datetime_attr(instrument, "expiry")
    option_type = _get_str_attr(instrument, "option_type")
    if strike is None or expiry is None or option_type is None:
        return None

    now = msg.timestamp_utc
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    seconds_to_expiry = (expiry - now).total_seconds()
    if seconds_to_expiry <= 0:
        return None

    time_to_expiry = Decimal(str(seconds_to_expiry / _SECONDS_PER_YEAR))
    # Resolve IV: msg.implied_volatility for CeFi (Deribit provides IV directly).
    # TradFi path (implied_vol_from_price) requires underlying_spot in schema — see plan.
    iv = msg.implied_volatility
    if iv is None or iv <= Decimal(0):
        return None
    return strike, time_to_expiry, str(option_type).upper(), iv, msg.dividend_yield or Decimal(0)


def _unpack_greeks(
    result: GreekResult | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    """Return (delta, gamma, theta, vega, rho) from a GreekResult, or all-None if absent."""
    if result is None:
        return None, None, None, None, None
    return result.delta, result.gamma, result.theta, result.vega, result.rho


def _make_event_id(source_event_id: str) -> str:
    """Derive a greeks-service event_id from the MTDS source_event_id."""
    if source_event_id:
        return f"{source_event_id}.greeks"
    return f"greeks-{uuid.uuid4().hex}"


def _resolve_asset_class(instrument: object | None) -> AssetClass:
    """Return the asset_class from InstrumentRecord, defaulting to UNKNOWN."""
    if instrument is None:
        return AssetClass.UNKNOWN
    ac = _get_str_attr(instrument, "asset_class")
    if ac is None:
        return AssetClass.UNKNOWN
    try:
        return AssetClass(ac.lower())
    except ValueError:
        return AssetClass.UNKNOWN


def _get_decimal_attr(obj: object, name: str) -> Decimal | None:
    val: object = cast(object, getattr(obj, name, None))
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _get_datetime_attr(obj: object, name: str) -> datetime | None:
    val: object = cast(object, getattr(obj, name, None))
    if isinstance(val, datetime):
        return val
    return None


def _get_str_attr(obj: object, name: str) -> str | None:
    val: object = cast(object, getattr(obj, name, None))
    if val is None:
        return None
    s = str(val)
    return s if s else None
