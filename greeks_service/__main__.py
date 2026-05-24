"""greeks-service CLI entry point.

ServiceBootstrap (from unified_trading_library) handles all infrastructure including the
STARTED / STOPPED / FAILED lifecycle triple (QG STEP 5.61).

Standard CLI flags provided by ServiceCLI (no service code needed):
  --operation (what), --mode (batch/live), --asset-group (domain),
  --start-date, --end-date, --log-level, --venues, --force, ...

SSOT for CLI convention: codex/06-coding-standards/cli-convention.md.

Phase 3: MarkUpdateHandler wired with Pub/Sub subscriber, IS reader, and
PricingLedger writer. Service loops on ``mark-update`` subscription.
See plans/active/pricing_ledger_carry_rates_mtds_2026_06_01.md Phase 3.
"""

from __future__ import annotations

import logging
import time

from unified_trading_library import GCSEventSink, ServiceBootstrap, log_event, setup_events

from greeks_service.config import get_greeks_config
from greeks_service.handlers.mark_update_handler import MarkUpdateHandler
from greeks_service.inputs.instrument_reader import InstrumentReader
from greeks_service.inputs.mark_update_sub import MarkUpdateSubscriber
from greeks_service.outputs.pricing_ledger_writer import PricingLedgerWriter

logger = logging.getLogger(__name__)
_SERVICE_NAME = "greeks-service"
_POLL_INTERVAL_SECONDS = 1.0
_EMPTY_POLL_BACKOFF_SECONDS = 5.0


def build_mark_update_operation() -> object:
    """Build the mark_update polling operation for the live subscription loop.

    Returns a callable compatible with ServiceBootstrap operations dict.
    """
    from unified_trading_library.cloud_interface import (  # noqa: qg-deep-import, imports-inside-functions
        get_message_bus,
    )

    cfg = get_greeks_config()

    bus = get_message_bus()
    subscriber = MarkUpdateSubscriber(
        bus=bus,  # type: ignore[arg-type]
        subscription=cfg.mark_update_subscription,
        max_messages=cfg.mark_update_max_messages,
    )
    reader = InstrumentReader(
        base_url=cfg.instruments_service_url,
        ttl_seconds=cfg.instruments_cache_ttl_seconds,
    )
    writer = PricingLedgerWriter(sink_bucket=cfg.pricing_ledger_sink_bucket)
    handler = MarkUpdateHandler(instrument_reader=reader, pricing_ledger_writer=writer)

    def _poll_loop() -> None:  # pragma: no cover
        log_event("PROCESSING_STARTED", details={"subscription": cfg.mark_update_subscription})
        consecutive_empty = 0
        while True:
            dispatched = subscriber.pull_and_dispatch(handler.handle)
            if dispatched > 0:
                consecutive_empty = 0
                log_event(
                    "PROCESSING_COMPLETED",
                    details={"messages_processed": dispatched},
                )
                time.sleep(_POLL_INTERVAL_SECONDS)
            else:
                consecutive_empty += 1
                backoff = min(_EMPTY_POLL_BACKOFF_SECONDS * consecutive_empty, 30.0)
                time.sleep(backoff)

    return _poll_loop


def main_service_cli() -> None:  # pragma: no cover
    """ServiceBootstrap entry point for greeks-service."""
    cfg = get_greeks_config()
    sink = GCSEventSink(
        project_id=cfg.gcp_project_id,
        bucket=f"{cfg.gcp_project_id}-events",
        service_name=_SERVICE_NAME,
    )
    setup_events(service_name=_SERVICE_NAME, mode="live", sink=sink)
    log_event(
        "STARTED",
        details={"service": _SERVICE_NAME, "phase": "3-live-subscriber"},
    )
    ServiceBootstrap(
        service_name=_SERVICE_NAME,
        operations={"mark_update": build_mark_update_operation()},
        config=get_greeks_config(),
    ).run()


if __name__ == "__main__":  # pragma: no cover
    main_service_cli()
