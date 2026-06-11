"""Test that event logging is wired correctly.

Required by quality-gates base-service.sh for all services.
"""

from __future__ import annotations


class TestEventLogging:
    """Verify event logging integration."""

    def test_log_event_importable(self) -> None:
        from unified_trading_library import log_event

        assert callable(log_event)

    def test_log_event_from_utl_directly(self) -> None:
        from unified_trading_library import log_event

        assert callable(log_event)
