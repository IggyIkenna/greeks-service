"""Unit tests for greeks-service config."""

from greeks_service.config import GreeksServiceConfig


def test_config_service_name() -> None:
    """Test that config loads with correct service name."""
    config = GreeksServiceConfig()
    assert config.service_name == "greeks-service"
