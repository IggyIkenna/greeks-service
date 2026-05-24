"""Batch-mode greeks computation from historical MTDS mark_update parquets.

Reads archived mark_update parquets from GCS, processes each row through the
same MarkUpdateHandler used in live mode, and writes PricingLedger rows.

This is the batch adapter in the Batch=Live model:
  Live:  MarkUpdateSubscriber (Pub/Sub) → MarkUpdateHandler → PricingLedgerWriter
  Batch: GreeksBackfillProcessor (GCS parquet) → MarkUpdateHandler → PricingLedgerWriter

Same kernels, same handler, same LedgerRow output. The only difference is the
input adapter and the batch filename_suffix for concurrent write isolation.

GCS parquet path (MTDS mark_update archive):
  mark_update/asset_group={ag}/date={YYYY-MM-DD}/*.parquet

Each parquet row has the same schema as the mark_update Pub/Sub payload (produced
by MTDS MarkUpdatePublisher): instrument_id, mark_price, implied_volatility,
timestamp_utc, venue_id, asset_group, dividend_yield, rebase_rate, funding_rate,
lending_rate, borrow_rate, staking_apy, source_event_id.

VM lifecycle: EPHEMERAL_BATCH (prefix: greeks-compute-batch- in vm_zombie_watchdog.py).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator

from unified_api_contracts import LedgerRow
from unified_trading_library import download_from_storage, get_storage_client

from greeks_service.handlers.mark_update_handler import MarkUpdateHandler
from greeks_service.inputs.instrument_reader import InstrumentReader
from greeks_service.inputs.mark_update_sub import MarkUpdateMessage
from greeks_service.kernels.black_scholes import BlackScholesKernel
from greeks_service.outputs.pricing_ledger_writer import PricingLedgerWriter

logger = logging.getLogger(__name__)

# GCS prefix under which MTDS archives mark_update payloads as parquet
_MARK_UPDATE_GCS_PREFIX = "mark_update"


def _dec(raw: object) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def _row_to_message(row: dict[str, object]) -> MarkUpdateMessage | None:
    """Convert a parquet row dict to MarkUpdateMessage; return None for invalid rows."""
    try:
        instrument_id = str(row["instrument_id"])
        mark_price_raw = row.get("mark_price")
        if mark_price_raw is None:
            return None
        mark_price = _dec(mark_price_raw)
        if mark_price is None or mark_price <= Decimal(0):
            return None

        ts_raw = row.get("timestamp_utc")
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        elif isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw)
        else:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        venue_id = str(row.get("venue_id") or "")
        asset_group = str(row.get("asset_group") or "")
        source_event_id = str(row.get("source_event_id") or "")

        return MarkUpdateMessage(
            instrument_id=instrument_id,
            mark_price=mark_price,
            implied_volatility=_dec(row.get("implied_volatility")),
            timestamp_utc=ts,
            venue_id=venue_id,
            asset_group=asset_group,
            dividend_yield=_dec(row.get("dividend_yield")),
            rebase_rate=_dec(row.get("rebase_rate")),
            funding_rate=_dec(row.get("funding_rate")),
            lending_rate=_dec(row.get("lending_rate")),
            borrow_rate=_dec(row.get("borrow_rate")),
            staking_apy=_dec(row.get("staking_apy")),
            source_event_id=source_event_id,
        )
    except (KeyError, TypeError, ValueError):
        logger.debug("_row_to_message: skipping malformed row keys=%s", list(row.keys()))
        return None


def _read_parquet_rows(bucket: str, gcs_path: str) -> list[dict[str, object]]:
    """Download a parquet from GCS and return as list of row dicts."""
    import io  # noqa: imports-inside-functions

    import pyarrow.parquet as pq  # noqa: imports-inside-functions

    data = download_from_storage(bucket, gcs_path)
    table = pq.read_table(io.BytesIO(data))
    col_names = table.schema.names
    return [{col: table.column(col)[i].as_py() for col in col_names} for i in range(table.num_rows)]


def _iter_parquet_paths(bucket: str, asset_group: str, target_date: date) -> Iterator[str]:
    """Yield GCS object paths for the given asset_group and date."""
    prefix = f"{_MARK_UPDATE_GCS_PREFIX}/asset_group={asset_group}/date={target_date.isoformat()}/"
    try:
        sc = get_storage_client()
        blobs = sc.list_blobs(bucket, prefix)
        for blob in blobs:
            # blob is BlobMetadata; name attr is the object path
            name = blob.name if hasattr(blob, "name") else str(blob)
            if name.endswith(".parquet"):
                yield name
    except Exception:
        logger.warning("_iter_parquet_paths: no objects found under gs://%s/%s", bucket, prefix)


class GreeksBackfillProcessor:
    """Batch greeks processor over a GCS mark_update parquet horizon.

    Args:
        handler: MarkUpdateHandler (same as live mode).
        source_bucket: GCS bucket holding MTDS mark_update parquets.
    """

    def __init__(
        self,
        handler: MarkUpdateHandler,
        source_bucket: str,
    ) -> None:
        self._handler = handler
        self._source_bucket = source_bucket

    def process_date(
        self,
        asset_group: str,
        target_date: date,
    ) -> list[LedgerRow]:
        """Process all mark_update parquets for asset_group × date.

        Returns:
            List of LedgerRow written to PricingLedger.
        """
        rows: list[LedgerRow] = []
        parquet_count = 0
        skip_count = 0

        for path in _iter_parquet_paths(self._source_bucket, asset_group, target_date):
            parquet_count += 1
            try:
                raw_rows = _read_parquet_rows(self._source_bucket, path)
            except Exception:
                logger.exception("GreeksBackfillProcessor: failed to read %s — skipping shard", path)
                continue

            for raw in raw_rows:
                msg = _row_to_message(raw)
                if msg is None:
                    skip_count += 1
                    continue
                try:
                    ledger_row = self._handler.handle(msg)
                    rows.append(ledger_row)
                except Exception:
                    logger.exception(
                        "GreeksBackfillProcessor: handler failed for instrument_id=%r — skipping",
                        raw.get("instrument_id"),
                    )
                    skip_count += 1

        logger.info(
            "GreeksBackfillProcessor: asset_group=%s date=%s parquets=%d rows=%d skipped=%d",
            asset_group,
            target_date,
            parquet_count,
            len(rows),
            skip_count,
        )
        return rows


def run_backfill(
    *,
    asset_group: str,
    target_date: date,
    source_bucket: str,
    instrument_reader: InstrumentReader,
    pricing_ledger_writer: PricingLedgerWriter,
    risk_free_rate: Decimal = Decimal("0.05"),
) -> int:
    """Entry point for batch backfill: wire handler + processor and run one date.

    Args:
        asset_group: Asset group to process (cefi/defi/tradfi).
        target_date: Date to backfill.
        source_bucket: GCS bucket for MTDS mark_update parquet archives.
        instrument_reader: IS reader for InstrumentRecord lookups.
        pricing_ledger_writer: PricingLedger GCS writer.
        risk_free_rate: Risk-free rate for Black-Scholes (default 5%).

    Returns:
        Number of PricingLedger rows written.
    """
    handler = MarkUpdateHandler(
        instrument_reader=instrument_reader,
        pricing_ledger_writer=pricing_ledger_writer,
        kernel=BlackScholesKernel(),
        risk_free_rate=risk_free_rate,
    )
    processor = GreeksBackfillProcessor(handler=handler, source_bucket=source_bucket)
    rows = processor.process_date(asset_group=asset_group, target_date=target_date)
    return len(rows)
