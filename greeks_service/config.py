"""Configuration for greeks-service.

Extends UnifiedCloudConfig (from unified-trading-library) for standardised configuration.
Typed config class — required by QG STEP 5.34 (config_reloaders MUST consume a typed config,
never bare ``object`` / ``getattr(service_config, ...)`` paths).

SSOT: codex/06-coding-standards/config-reloader-pattern.md
"""

from __future__ import annotations

from pydantic import AliasChoices, ConfigDict, Field
from unified_trading_library import UnifiedCloudConfig, load_config


class GreeksServiceConfig(UnifiedCloudConfig):
    """Service-level configuration for greeks-service.

    Phase 1 stub: only the fields needed to wire ServiceBootstrap + DomainConfigReloader.
    Phase 2+ extends with greeks-calculator parameters (rate curves, vol surface sources)
    and PricingLedger write-bucket bindings.
    """

    model_config = ConfigDict(extra="allow")

    service_name: str = Field(default="greeks-service", description="Service name")

    config_store_bucket: str = Field(
        default="",
        validation_alias=AliasChoices("CONFIG_STORE_BUCKET"),
        description="Cloud storage bucket for dynamic domain config store hot-reload",
    )

    market_data_source_bucket: str = Field(
        default="",
        validation_alias=AliasChoices("MARKET_DATA_GCS_BUCKET"),
        description="Source bucket for MTDS mark prices (input)",
    )

    instruments_source_bucket: str = Field(
        default="",
        validation_alias=AliasChoices("INSTRUMENTS_GCS_BUCKET"),
        description="Source bucket for instruments-service instrument metadata (input)",
    )

    pricing_ledger_sink_bucket: str = Field(
        default="",
        validation_alias=AliasChoices("PRICING_LEDGER_GCS_BUCKET"),
        description="Sink bucket for PricingLedger rows (output)",
    )


_config: GreeksServiceConfig | None = None


def get_greeks_config() -> GreeksServiceConfig:
    """Return the singleton service config instance."""
    global _config
    if _config is None:
        _config = load_config(GreeksServiceConfig)
    return _config
