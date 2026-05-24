"""Unit tests for pricing_ledger_writer.py.

Covers:
- _rows_to_parquet: single LedgerRow → valid parquet bytes
- _rows_to_parquet: multiple rows → correct row count
- _rows_to_parquet: empty list raises / returns empty bytes
- _ledger_row_to_dict: Decimal fields converted to str
- _ledger_row_to_dict: enum fields converted to str
- PricingLedgerWriter.write: empty rows → no-op (no upload call)
- PricingLedgerWriter.write: calls upload_to_storage with correct path
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pyarrow.parquet as pq

from greeks_service.outputs.pricing_ledger_writer import (
    PricingLedgerWriter,
    _ledger_row_to_dict,
    _rows_to_parquet,
)


def _make_row(
    instrument_id: str = "BINANCE:OPTION:ETH-3000-C",
    mark_price: str = "3200.00",
    option_delta: str | None = None,
    asset_group: str = "cefi",
) -> object:
    """Build a minimal MARK_UPDATE LedgerRow for test purposes."""
    from unified_api_contracts import EventOrigin, EventType, LedgerRow
    from unified_api_contracts import LedgerAssetClass as AssetClass

    ts = datetime(2024, 12, 15, 12, 0, 0, tzinfo=UTC)
    event_id = f"greeks-{instrument_id}.0"
    return LedgerRow(
        event_id=event_id,
        row_id=f"{event_id}.0",
        event_origin=EventOrigin.PASSIVE,
        event_type=EventType.MARK_UPDATE,
        timestamp_utc=ts,
        asset_group=asset_group,
        venue="BINANCE",
        account_id="_pricing_ledger",
        client_id="_pricing",
        asset_symbol="ETH",
        asset_canonical_id=instrument_id,
        asset_class=AssetClass.SPOT_TOKEN,
        delta=Decimal(0),
        price=Decimal(mark_price),
        option_delta=Decimal(option_delta) if option_delta else None,
    )


class TestRowsToParquet:
    def test_single_row_produces_valid_parquet(self) -> None:
        row = _make_row()
        result = _rows_to_parquet([row])
        assert isinstance(result, bytes)
        assert len(result) > 0
        # Verify it's valid parquet by reading back
        import io

        table = pq.read_table(io.BytesIO(result))
        assert len(table) == 1

    def test_multiple_rows_correct_count(self) -> None:
        rows = [_make_row(instrument_id=f"BINANCE:OPTION:ETH-{i}-C") for i in range(5)]
        result = _rows_to_parquet(rows)
        import io

        table = pq.read_table(io.BytesIO(result))
        assert len(table) == 5

    def test_wrong_type_raises(self) -> None:
        import pytest

        with pytest.raises(TypeError):
            _rows_to_parquet(["not-a-ledger-row"])  # type: ignore[list-item]


class TestLedgerRowToDict:
    def test_decimal_fields_serialized_as_str(self) -> None:
        row = _make_row(mark_price="3200.00", option_delta="0.65")
        d = _ledger_row_to_dict(row)
        assert isinstance(d["price"], str)
        assert d["price"] == "3200.00"
        assert isinstance(d["option_delta"], str)
        assert d["option_delta"] == "0.65"

    def test_none_decimal_remains_none(self) -> None:
        row = _make_row()
        d = _ledger_row_to_dict(row)
        assert d["option_delta"] is None
        assert d["rebase_rate"] is None

    def test_delta_zero_serialized_correctly(self) -> None:
        row = _make_row()
        d = _ledger_row_to_dict(row)
        assert d["delta"] == "0"

    def test_wrong_type_raises(self) -> None:
        import pytest

        with pytest.raises(TypeError):
            _ledger_row_to_dict("not-a-ledger-row")  # type: ignore[arg-type]


class TestPricingLedgerWriter:
    def test_empty_rows_is_noop(self) -> None:
        writer = PricingLedgerWriter(sink_bucket="test-bucket")
        with patch("greeks_service.outputs.pricing_ledger_writer.upload_to_storage") as mock_upload:
            writer.write([], asset_group="cefi")
            mock_upload.assert_not_called()

    def test_calls_upload_with_correct_path(self) -> None:
        from datetime import date

        writer = PricingLedgerWriter(sink_bucket="my-pricing-bucket")
        row = _make_row()
        with patch("greeks_service.outputs.pricing_ledger_writer.upload_to_storage") as mock_upload:
            writer.write([row], asset_group="cefi", event_date=date(2024, 12, 15))
            mock_upload.assert_called_once()
            call_args = mock_upload.call_args
            bucket, path, data = call_args.args
            assert bucket == "my-pricing-bucket"
            assert path.startswith("ledger_type=pricing/asset_group=cefi/date=2024-12-15/")
            assert path.endswith(".parquet")
            assert isinstance(data, bytes)

    def test_filename_suffix_included_in_path(self) -> None:
        from datetime import date

        writer = PricingLedgerWriter(sink_bucket="my-bucket")
        row = _make_row()
        with patch("greeks_service.outputs.pricing_ledger_writer.upload_to_storage") as mock_upload:
            writer.write([row], asset_group="defi", event_date=date(2024, 12, 15), filename_suffix="worker-1")
            _, path, _ = mock_upload.call_args.args
            assert "_worker-1" in path
