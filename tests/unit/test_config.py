"""Tests for greeks-service config."""

from __future__ import annotations

from greeks_service.config import GreeksServiceConfig, get_greeks_config


class TestGreeksServiceConfig:
    """Test GreeksServiceConfig defaults and singleton."""

    def test_defaults(self) -> None:
        config = GreeksServiceConfig()
        assert config.service_name == "greeks-service"
        assert config.config_store_bucket == ""
        assert config.pricing_ledger_sink_bucket == ""
        assert config.mark_update_subscription == "mark-update-greeks-sub"
        assert config.instruments_service_url == "http://instruments-service:8080"
        assert config.instruments_cache_ttl_seconds == 300
        assert config.mark_update_max_messages == 10

    def test_singleton(self) -> None:
        config1 = get_greeks_config()
        config2 = get_greeks_config()
        assert config1 is config2

    def test_service_fields_present(self) -> None:
        config = GreeksServiceConfig()
        expected = {
            "service_name",
            "config_store_bucket",
            "pricing_ledger_sink_bucket",
            "mark_update_subscription",
            "instruments_service_url",
            "instruments_cache_ttl_seconds",
            "mark_update_max_messages",
        }
        assert expected.issubset(set(config.model_fields.keys()))
