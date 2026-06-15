"""MTDS mark_update Pub/Sub subscriber for greeks-service.

Pulls messages from the MTDS `mark-update` topic subscription, decodes them
into MarkUpdateMessage objects, and dispatches to a handler callback.

Uses UTL MessageBus (cloud-agnostic: GCP Pub/Sub in prod; LocalMessageBus
in tests). Pull-based with explicit ack after successful handler dispatch.

Backpressure: configurable max_messages per pull batch.
Idempotency: handler must be idempotent; ack only after callback returns.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Callable, cast

if TYPE_CHECKING:
    from unified_trading_library.cloud_interface import MessageBus  # noqa: qg-deep-import

logger = logging.getLogger(__name__)

MessageCallback = Callable[["MarkUpdateMessage"], None]


@dataclass(frozen=True)
class MarkUpdateMessage:
    """Decoded MTDS mark_update Pub/Sub message payload.

    Fields mirror the MTDS mark_update topic payload (see
    codex/04-architecture/greeks-service-overview.md § Inputs).
    """

    instrument_id: str
    mark_price: Decimal
    implied_volatility: Decimal | None
    timestamp_utc: datetime
    venue_id: str
    asset_group: str
    # Carry rates pre-computed by MTDS (None for non-applicable instruments)
    dividend_yield: Decimal | None
    rebase_rate: Decimal | None
    funding_rate: Decimal | None
    lending_rate: Decimal | None
    borrow_rate: Decimal | None
    staking_apy: Decimal | None
    # Source event ID from MTDS — used as parent_event_id on PricingLedger rows
    source_event_id: str


class MarkUpdateSubscriber:
    """Pull-based subscriber for the MTDS mark_update Pub/Sub topic.

    Args:
        bus: MessageBus instance (from get_message_bus()).
        subscription: Subscription name for the mark-update topic.
        max_messages: Max messages to pull per batch.
    """

    def __init__(
        self,
        bus: MessageBus,
        subscription: str,
        max_messages: int = 10,
    ) -> None:
        self._bus = bus
        self._subscription = subscription
        self._max_messages = max_messages

    def pull_and_dispatch(self, callback: MessageCallback) -> int:
        """Pull one batch of messages and dispatch each to callback.

        Acks only messages for which callback succeeds without raising.

        Returns:
            Number of messages successfully dispatched (and acked).
        """
        messages = self._bus.pull(self._subscription, max_messages=self._max_messages)
        dispatched = 0
        ack_ids: list[str] = []
        for msg in messages:
            try:
                payload = decode_mark_update(msg.data)
                callback(payload)
                ack_ids.append(msg.ack_id)
                dispatched += 1
            except Exception:
                logger.exception(
                    "mark_update_sub: dispatch failed for message_id=%s — skipping ack",
                    msg.message_id,
                )
        if ack_ids:
            self._bus.acknowledge(self._subscription, ack_ids)
        return dispatched


def decode_mark_update(data: bytes) -> MarkUpdateMessage:
    """Decode raw Pub/Sub bytes into MarkUpdateMessage.

    Raises:
        KeyError: if required fields are missing.
        ValueError / DecimalException: if numeric fields are malformed.
    """
    raw: dict[str, object] = cast(dict[str, object], json.loads(data.decode("utf-8")))
    ts_raw = raw["timestamp_utc"]
    if not isinstance(ts_raw, str):
        raise ValueError(f"timestamp_utc must be a string, got {type(ts_raw)}")
    ts = datetime.fromisoformat(ts_raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)

    def _dec(key: str) -> Decimal | None:
        v = raw.get(key)
        return Decimal(str(v)) if v is not None else None

    mark_price_raw = raw["mark_price"]
    instrument_id_raw = raw["instrument_id"]
    venue_id_raw = raw["venue_id"]
    asset_group_raw = raw["asset_group"]

    return MarkUpdateMessage(
        instrument_id=str(instrument_id_raw),
        mark_price=Decimal(str(mark_price_raw)),
        implied_volatility=_dec("implied_volatility"),
        timestamp_utc=ts,
        venue_id=str(venue_id_raw),
        asset_group=str(asset_group_raw),
        dividend_yield=_dec("dividend_yield"),
        rebase_rate=_dec("rebase_rate"),
        funding_rate=_dec("funding_rate"),
        lending_rate=_dec("lending_rate"),
        borrow_rate=_dec("borrow_rate"),
        staking_apy=_dec("staking_apy"),
        source_event_id=str(raw.get("source_event_id", "")),  # noqa: qg-empty-fallback
    )
