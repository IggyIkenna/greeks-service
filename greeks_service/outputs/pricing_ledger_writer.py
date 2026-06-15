"""PricingLedger GCS writer for greeks-service.

Appends LedgerRow (event_type=MARK_UPDATE) batches to the PricingLedger
GCS parquet sink.

Partition layout:
    ledger_type=pricing/asset_group=<group>/date=<YYYY-MM-DD>/<filename>.parquet

Bucket is supplied at construction time from GreeksServiceConfig.pricing_ledger_sink_bucket
(raw bucket name from config). Bucket-kind canonicalisation via resolve_bucket_name()
is DEFERRED (P1 — blocked on bucket-SSOT stabilisation per plan Phase 0 INFRA item).

Storage writes via upload_to_storage() from unified_trading_library — never a
hardcoded bucket URI literal (QG STEP 5.69).
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, date, datetime
from typing import cast

from unified_api_contracts import LedgerRow
from unified_trading_library import upload_to_storage

logger = logging.getLogger(__name__)

_LEDGER_TYPE = "pricing"


class PricingLedgerWriter:
    """Appends MARK_UPDATE LedgerRow records to the PricingLedger GCS parquet sink.

    Args:
        sink_bucket: Raw GCS bucket name for PricingLedger output.
    """

    def __init__(self, sink_bucket: str) -> None:
        self._sink_bucket = sink_bucket

    def write(
        self,
        rows: list[object],
        asset_group: str,
        event_date: date | None = None,
        filename_suffix: str = "",
    ) -> None:
        """Write a batch of LedgerRow objects to PricingLedger GCS parquet.

        Args:
            rows: List of LedgerRow (event_type=MARK_UPDATE).
            asset_group: Asset group discriminant (cefi/defi/tradfi/sports/prediction).
            event_date: Date partition key (defaults to today in UTC).
            filename_suffix: Optional suffix to distinguish concurrent writers.
        """
        if not rows:
            return

        if event_date is None:
            event_date = datetime.now(UTC).date()

        prefix = f"ledger_type={_LEDGER_TYPE}/asset_group={asset_group}/date={event_date.isoformat()}/"
        suffix = f"_{filename_suffix}" if filename_suffix else ""
        filename = f"mark_update_{asset_group}_{event_date.isoformat()}{suffix}.parquet"
        path = f"{prefix}{filename}"

        parquet_bytes = _rows_to_parquet(rows)
        try:
            upload_to_storage(self._sink_bucket, path, parquet_bytes)
            logger.info(
                "PricingLedgerWriter: wrote %d rows to %s/%s",
                len(rows),
                self._sink_bucket,
                path,
            )
        except Exception:
            logger.exception(
                "PricingLedgerWriter: failed to write %d rows to %s/%s",
                len(rows),
                self._sink_bucket,
                path,
            )
            raise


def _dataframe_to_parquet_bytes(records: list[dict[str, object]]) -> bytes:
    """Serialise records to parquet bytes via pandas (uses pyarrow engine internally)."""
    import pandas as pd  # noqa: imports-inside-functions

    df = pd.DataFrame(records)
    buf = io.BytesIO()
    df.to_parquet(buf, engine="pyarrow", index=False)
    buf.seek(0)
    return buf.read()


def _rows_to_parquet(rows: list[object]) -> bytes:
    """Serialize a list of LedgerRow objects to parquet bytes."""
    records: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, LedgerRow):
            records.append(_ledger_row_to_dict(row))
        else:
            raise TypeError(f"Expected LedgerRow, got {type(row)}")
    return _dataframe_to_parquet_bytes(records)


def _ledger_row_to_dict(row: object) -> dict[str, object]:
    """Convert a LedgerRow to a dict suitable for pandas DataFrame construction."""
    if not isinstance(row, LedgerRow):
        raise TypeError(f"Expected LedgerRow, got {type(row)}")

    # model_dump() returns dict[str, Any]; cast to dict[str, object] at the pydantic boundary
    d: dict[str, object] = cast(dict[str, object], row.model_dump())
    # Convert Decimal to str for parquet compatibility
    decimal_fields = [
        "delta",
        "price",
        "fees_in_quote",
        "strike",
        "combo_price",
        "option_delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "funding_rate",
        "lending_rate",
        "borrow_rate",
        "staking_apy",
        "dividend_yield",
        "rebase_rate",
    ]
    for field_name in decimal_fields:
        v: object = d.get(field_name)
        if v is not None:
            d[field_name] = str(v)

    # Convert enums to string values
    for key, val in d.items():
        val_obj: object = val
        if hasattr(val_obj, "value"):
            d[key] = str(val_obj)

    return d
