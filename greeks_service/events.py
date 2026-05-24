"""Event declarations for greeks-service.

Documents which lifecycle events this service emits via ServiceBootstrap +
fastapi_uei_lifespan. Phase 1: lifecycle triple only. Phase 2+ adds
computation-pipeline events (VALIDATION_*, DATA_INGESTION_*, PROCESSING_*,
PERSISTENCE_*) as GreeksComputationHandler is wired in.

See: plans/active/global_ledger_pnl_attribution_migration_2026_06_01.md

SERVICE_EVENT: STARTED
SERVICE_EVENT: STOPPED
SERVICE_EVENT: FAILED
SERVICE_EVENT: VALIDATION_STARTED
SERVICE_EVENT: VALIDATION_COMPLETED
SERVICE_EVENT: VALIDATION_FAILED
SERVICE_EVENT: DATA_INGESTION_STARTED
SERVICE_EVENT: DATA_INGESTION_COMPLETED
SERVICE_EVENT: PROCESSING_STARTED
SERVICE_EVENT: PROCESSING_COMPLETED
SERVICE_EVENT: PERSISTENCE_STARTED
SERVICE_EVENT: PERSISTENCE_COMPLETED
"""

from unified_trading_library import log_event

__all__ = ["log_event"]
