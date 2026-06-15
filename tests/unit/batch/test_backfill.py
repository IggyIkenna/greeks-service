"""Unit tests for greeks_service/batch/backfill.py.

Covers:
- _row_to_message: valid row → MarkUpdateMessage
- _row_to_message: missing/invalid mark_price → None
- _row_to_message: missing instrument_id → None
- _row_to_message: None timestamp → None
- GreeksBackfillProcessor.process_date: all rows processed, returns dispatched count (int)
- GreeksBackfillProcessor.process_date: malformed rows skipped
- run_backfill: returns correct count

Note: process_date() returns int (dispatched row count), not a list.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from greeks_service.batch.backfill import (
    GreeksBackfillProcessor,
    _dec,
    _read_parquet_rows,
    _row_to_message,
    run_backfill,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_NOW = datetime(2024, 12, 15, 12, 0, 0, tzinfo=UTC)
_EXPIRY = _NOW + timedelta(days=30)


def _make_valid_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "instrument_id": "DERIBIT:OPTION:ETH-31DEC24-3000-C",
        "mark_price": "3200.00",
        "implied_volatility": "0.65",
        "timestamp_utc": _NOW.isoformat(),
        "venue_id": "DERIBIT",
        "asset_group": "cefi",
        "source_event_id": "evt-abc",
        "dividend_yield": None,
        "rebase_rate": None,
        "funding_rate": None,
        "lending_rate": None,
        "borrow_rate": None,
        "staking_apy": None,
    }
    row.update(overrides)
    return row


# ── _row_to_message ───────────────────────────────────────────────────────────


class TestRowToMessage:
    def test_valid_row_returns_message(self) -> None:
        row = _make_valid_row()
        msg = _row_to_message(row)
        assert msg is not None
        assert msg.instrument_id == "DERIBIT:OPTION:ETH-31DEC24-3000-C"
        assert msg.mark_price == Decimal("3200.00")
        assert msg.implied_volatility == Decimal("0.65")
        assert msg.venue_id == "DERIBIT"
        assert msg.asset_group == "cefi"

    def test_missing_mark_price_returns_none(self) -> None:
        row = _make_valid_row()
        del row["mark_price"]
        assert _row_to_message(row) is None

    def test_zero_mark_price_returns_none(self) -> None:
        assert _row_to_message(_make_valid_row(mark_price="0.0")) is None

    def test_negative_mark_price_returns_none(self) -> None:
        assert _row_to_message(_make_valid_row(mark_price="-1.0")) is None

    def test_invalid_mark_price_string_returns_none(self) -> None:
        assert _row_to_message(_make_valid_row(mark_price="not-a-number")) is None

    def test_missing_instrument_id_returns_none(self) -> None:
        row = _make_valid_row()
        del row["instrument_id"]
        assert _row_to_message(row) is None

    def test_none_timestamp_returns_none(self) -> None:
        row = _make_valid_row(timestamp_utc=None)
        assert _row_to_message(row) is None

    def test_carry_rates_none_pass_through(self) -> None:
        msg = _row_to_message(_make_valid_row())
        assert msg is not None
        assert msg.funding_rate is None
        assert msg.dividend_yield is None

    def test_carry_rates_populated(self) -> None:
        msg = _row_to_message(_make_valid_row(funding_rate="0.0001", staking_apy="0.05"))
        assert msg is not None
        assert msg.funding_rate == Decimal("0.0001")
        assert msg.staking_apy == Decimal("0.05")

    def test_timestamp_tz_naive_gets_utc(self) -> None:
        naive_ts = "2024-12-15T12:00:00"
        msg = _row_to_message(_make_valid_row(timestamp_utc=naive_ts))
        assert msg is not None
        assert msg.timestamp_utc.tzinfo is not None

    def test_datetime_object_timestamp(self) -> None:
        msg = _row_to_message(_make_valid_row(timestamp_utc=_NOW))
        assert msg is not None
        assert msg.timestamp_utc == _NOW


# ── GreeksBackfillProcessor ───────────────────────────────────────────────────


class TestGreeksBackfillProcessor:
    def _make_processor(
        self,
        handler: object,
    ) -> GreeksBackfillProcessor:
        return GreeksBackfillProcessor(handler=handler, source_bucket="test-bucket")  # type: ignore[arg-type]

    def test_process_date_calls_handler_for_each_row(self) -> None:
        from unittest.mock import MagicMock

        mock_handler = MagicMock()
        mock_handler.handle.return_value = None  # handle() returns None

        valid_row = _make_valid_row()
        parquet_rows = [valid_row, valid_row]

        processor = self._make_processor(mock_handler)

        with (
            patch("greeks_service.batch.backfill._iter_parquet_paths", return_value=["p1.parquet"]),
            patch("greeks_service.batch.backfill._read_parquet_rows", return_value=parquet_rows),
        ):
            result = processor.process_date("cefi", date(2024, 12, 15))

        assert mock_handler.handle.call_count == 2
        assert result == 2  # int: dispatched count

    def test_process_date_skips_invalid_rows(self) -> None:
        mock_handler = MagicMock()
        mock_handler.handle.return_value = None  # handle() returns None

        rows = [
            _make_valid_row(),
            {"instrument_id": "bad", "mark_price": None},  # invalid — no mark_price
        ]

        processor = self._make_processor(mock_handler)

        with (
            patch("greeks_service.batch.backfill._iter_parquet_paths", return_value=["p1.parquet"]),
            patch("greeks_service.batch.backfill._read_parquet_rows", return_value=rows),
        ):
            result = processor.process_date("cefi", date(2024, 12, 15))

        assert mock_handler.handle.call_count == 1
        assert result == 1  # int: only the valid row was dispatched

    def test_process_date_no_parquets_returns_empty(self) -> None:
        mock_handler = MagicMock()
        processor = self._make_processor(mock_handler)

        with patch("greeks_service.batch.backfill._iter_parquet_paths", return_value=[]):
            result = processor.process_date("cefi", date(2024, 12, 15))

        assert result == 0  # int: 0 when no parquets found
        mock_handler.handle.assert_not_called()

    def test_process_date_handler_exception_skipped(self) -> None:
        mock_handler = MagicMock()
        mock_handler.handle.side_effect = RuntimeError("kernel exploded")

        processor = self._make_processor(mock_handler)

        with (
            patch("greeks_service.batch.backfill._iter_parquet_paths", return_value=["p1.parquet"]),
            patch("greeks_service.batch.backfill._read_parquet_rows", return_value=[_make_valid_row()]),
        ):
            result = processor.process_date("cefi", date(2024, 12, 15))

        assert result == 0  # int: handler failed → 0 dispatched

    def test_process_date_parquet_read_error_skipped(self) -> None:
        mock_handler = MagicMock()
        processor = self._make_processor(mock_handler)

        with (
            patch("greeks_service.batch.backfill._iter_parquet_paths", return_value=["broken.parquet"]),
            patch("greeks_service.batch.backfill._read_parquet_rows", side_effect=OSError("gcs down")),
        ):
            result = processor.process_date("cefi", date(2024, 12, 15))

        assert result == 0  # int: read error → 0 dispatched
        mock_handler.handle.assert_not_called()


# ── run_backfill ──────────────────────────────────────────────────────────────


class TestRunBackfill:
    def test_run_backfill_returns_row_count(self) -> None:
        from greeks_service.inputs.instrument_reader import InstrumentReader

        reader = InstrumentReader(base_url="http://localhost", mock_fetcher=lambda _: None)
        mock_writer = MagicMock()

        with (
            patch("greeks_service.batch.backfill._iter_parquet_paths", return_value=["p.parquet"]),
            patch(
                "greeks_service.batch.backfill._read_parquet_rows",
                return_value=[_make_valid_row(), _make_valid_row()],
            ),
        ):
            count = run_backfill(
                asset_group="cefi",
                target_date=date(2024, 12, 15),
                source_bucket="test-bucket",
                instrument_reader=reader,
                pricing_ledger_writer=mock_writer,
            )

        # No instrument → no greeks → but LedgerRow still emitted (carry passthrough)
        assert count == 2


# ── Regression: pandas NaN/NaT coercion (2026-06-15) ──────────────────────────
# pd.read_parquet().to_dict() yields np.nan/NaT for NULL cells (not None). Without the
# NaN→None map in _read_parquet_rows + the is_nan() guard in _dec, a null mark_price
# became Decimal("NaN") (crashed the `<= 0` ordered compare → aborted the backfill) and
# null optional rates leaked Decimal("NaN") into Black-Scholes. Guards reintroduction.


class TestNullCoercionRegression:
    def test_dec_nan_returns_none(self) -> None:
        assert _dec(float("nan")) is None

    def test_nan_mark_price_skipped_not_crash(self) -> None:
        # would raise decimal.InvalidOperation before the fix
        assert _row_to_message(_make_valid_row(mark_price=float("nan"))) is None

    def test_nan_optional_rates_become_none(self) -> None:
        msg = _row_to_message(_make_valid_row(funding_rate=float("nan"), staking_apy=float("nan")))
        assert msg is not None
        assert msg.funding_rate is None
        assert msg.staking_apy is None

    def test_read_parquet_rows_maps_nan_and_nat_to_none(self) -> None:
        import io

        import pyarrow as pa
        import pyarrow.parquet as pq

        schema = pa.schema([
            ("instrument_id", pa.string()),
            ("mark_price", pa.float64()),
            ("timestamp_utc", pa.timestamp("us", tz="UTC")),
        ])
        table = pa.table(
            {"instrument_id": ["A", "B"], "mark_price": [1.0, None], "timestamp_utc": [_NOW, None]},
            schema=schema,
        )
        buf = io.BytesIO()
        pq.write_table(table, buf)
        with patch("greeks_service.batch.backfill.download_from_storage", return_value=buf.getvalue()):
            rows = _read_parquet_rows("bucket", "path")
        assert rows[0]["mark_price"] == 1.0
        assert rows[1]["mark_price"] is None  # was np.nan
        assert rows[1]["timestamp_utc"] is None  # was NaT
