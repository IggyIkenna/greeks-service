"""Smoke test: greeks-service package imports cleanly."""

from __future__ import annotations

from datetime import date
from typing import cast

import pytest


@pytest.mark.smoke
def test_greeks_service_imports() -> None:
    """Package import succeeds — base sanity check for Phase 1 skeleton."""
    import greeks_service

    assert greeks_service.__doc__ is not None


@pytest.mark.smoke
def test_config_module_imports() -> None:
    """Typed config class is importable (QG STEP 5.34 prerequisite)."""
    from greeks_service.config import GreeksServiceConfig

    assert GreeksServiceConfig.__name__ == "GreeksServiceConfig"


@pytest.mark.smoke
def test_api_main_imports() -> None:
    """FastAPI app factory is importable (QG STEP 5.62 prerequisite)."""
    from greeks_service.api.main import create_app

    assert callable(create_app)


@pytest.mark.smoke
def test_config_reloaders_importable() -> None:
    """Config reloaders module imports cleanly; module-level globals initialized."""
    import greeks_service.config_reloaders as mod

    assert mod._active_instruments is None
    assert mod._instrument_reloader is None


@pytest.mark.smoke
def test_get_active_instruments_returns_none() -> None:
    """get_active_instruments() returns None before any reload."""
    from greeks_service.config_reloaders import get_active_instruments

    assert get_active_instruments() is None


@pytest.mark.smoke
def test_phase1_stub_stop_reloaders_raises() -> None:
    """Phase 1 stub: stop_domain_config_reloaders raises NotImplementedError."""
    from greeks_service.config_reloaders import stop_domain_config_reloaders

    with pytest.raises(NotImplementedError):
        stop_domain_config_reloaders()


@pytest.mark.smoke
def test_phase1_stub_on_instruments_reload_raises() -> None:
    """Phase 1 stub: _on_instruments_reload raises NotImplementedError."""
    from unified_trading_library import InstrumentDomainConfig

    from greeks_service.config_reloaders import _on_instruments_reload

    with pytest.raises(NotImplementedError):
        _on_instruments_reload(cast(InstrumentDomainConfig, None))


@pytest.mark.smoke
def test_uac_greeks_types_importable() -> None:
    """UAC domain types used by greeks computation are importable (dep alignment)."""
    from unified_api_contracts import PortfolioGreeksSnapshot

    assert PortfolioGreeksSnapshot.__name__ == "PortfolioGreeksSnapshot"


@pytest.mark.smoke
def test_set_last_processed_date() -> None:
    """set_last_processed_date stores the date; _data_freshness reflects it."""
    from greeks_service.api import main as api_main

    api_main.set_last_processed_date(date(2026, 5, 24))
    result = api_main._data_freshness()
    assert result["stale"] is False
    assert result["last_processed_date"] == "2026-05-24"
