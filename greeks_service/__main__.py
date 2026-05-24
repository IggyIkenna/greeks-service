"""greeks-service CLI entry point.

ServiceBootstrap (from unified_trading_library) handles all infrastructure including the
STARTED / STOPPED / FAILED lifecycle triple (QG STEP 5.61).

Standard CLI flags provided by ServiceCLI (no service code needed):
  --operation (what), --mode (batch/live), --asset-group (domain),
  --start-date, --end-date, --log-level, --venues, --force, ...

SSOT for CLI convention: codex/06-coding-standards/cli-convention.md.

Phase 1 stub: handler set is empty — Phase 2+ wires
``GreeksComputationHandler`` (compute + write PricingLedger rows) and
``CarryRateHandler`` (carry/funding/lending APR derivation).
See plans/active/global_ledger_pnl_attribution_migration_2026_06_01.md.
"""

from __future__ import annotations

from unified_trading_library import ServiceBootstrap, log_event, setup_events

from greeks_service.config import get_greeks_config

_SERVICE_NAME = "greeks-service"


def main_service_cli() -> None:  # pragma: no cover
    """ServiceBootstrap entry point for greeks-service."""
    setup_events(service_name=_SERVICE_NAME, mode="batch", sink=None)
    log_event(
        "STARTED",
        details={"service": _SERVICE_NAME, "phase": "1-skeleton"},
    )
    ServiceBootstrap(
        service_name=_SERVICE_NAME,
        operations={},
        config=get_greeks_config(),
    ).run()


if __name__ == "__main__":  # pragma: no cover
    main_service_cli()
