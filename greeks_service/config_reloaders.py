"""Domain config hot-reload wiring for greeks-service.

Instrument metadata + (future) vol-surface configs are reloaded at runtime via
DomainConfigReloader from unified_trading_library whenever the backing cloud storage
object is updated. Uses the typed GreeksServiceConfig — never ``object`` / dynamic
attribute lookup (QG STEP 5.34).

Phase 1 stub: function signatures only — real reloader wiring lands in Phase 2 of
``plans/active/global_ledger_pnl_attribution_migration_2026_06_01.md``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from unified_trading_library import (
    DomainConfigReloader,
    InstrumentDomainConfig,
)

if TYPE_CHECKING:
    from greeks_service.config import GreeksServiceConfig

logger = logging.getLogger(__name__)

_instrument_reloader: DomainConfigReloader[InstrumentDomainConfig] | None = None
_active_instruments: InstrumentDomainConfig | None = None


def get_active_instruments() -> InstrumentDomainConfig | None:
    """Return the latest hot-reloaded instrument domain config."""
    return _active_instruments


def start_domain_config_reloaders(service_config: GreeksServiceConfig) -> None:
    """Start domain config reloaders. Called on service startup — Phase 1 stub."""
    raise NotImplementedError(
        "greeks-service Phase 1 — see plans/active/global_ledger_pnl_attribution_migration_2026_06_01.md"
    )


def stop_domain_config_reloaders() -> None:
    """Stop domain config reloaders. Called on service shutdown — Phase 1 stub."""
    raise NotImplementedError(
        "greeks-service Phase 1 — see plans/active/global_ledger_pnl_attribution_migration_2026_06_01.md"
    )
