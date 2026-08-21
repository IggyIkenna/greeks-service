"""Domain config hot-reload wiring for greeks-service.

Instrument metadata + (future) vol-surface configs are reloaded at runtime via
DomainConfigReloader from unified_trading_library whenever the backing cloud storage
object is updated. Uses the typed GreeksServiceConfig — never ``object`` / dynamic
attribute lookup (QG STEP 5.34).

Phase 1 stub: function signatures only, never wired up. The plan this docstring
used to cite (``plans/active/global_ledger_pnl_attribution_migration_2026_06_01.md``)
never actually covered this wiring and is archived; investigation (2026-08-21) found
the instrument-metadata need this module was meant to serve was instead fulfilled by
``greeks_service.inputs.instrument_reader.InstrumentReader`` (HTTP + TTL cache
against instruments-service), shipped under
``plans/archive/2026_05/pricing_ledger_carry_rates_mtds_2026_06_01.md`` Phase 3
(status: complete). ``get_active_instruments()`` has zero callers. No active plan
currently owns wiring this DomainConfigReloader path — left unwired rather than
inventing new design intent.
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
    """Start domain config reloaders. Called on service startup — Phase 1 stub, unwired."""
    raise NotImplementedError(
        "greeks-service config_reloaders.py is an unwired Phase 1 stub — no active plan owns wiring it "
        "(instrument metadata is served instead via greeks_service.inputs.instrument_reader.InstrumentReader)"
    )


def stop_domain_config_reloaders() -> None:
    """Stop domain config reloaders. Called on service shutdown — Phase 1 stub, unwired."""
    raise NotImplementedError(
        "greeks-service config_reloaders.py is an unwired Phase 1 stub — no active plan owns wiring it "
        "(instrument metadata is served instead via greeks_service.inputs.instrument_reader.InstrumentReader)"
    )
