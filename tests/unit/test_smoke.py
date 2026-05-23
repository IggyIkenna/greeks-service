"""Smoke test: greeks-service package imports cleanly."""

from __future__ import annotations

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
