#!/usr/bin/env bash
# Repo-specific settings only. Body: unified-trading-pm/scripts/quality-gates-base/base-service.sh
# SSOT: unified-trading-pm/codex/06-coding-standards/quality-gates-service-template.sh
#
# Phase 1 skeleton: minimal settings — extends as handlers / adapters / scripts land in
# subsequent phases of plans/active/global_ledger_pnl_attribution_migration_2026_06_01.md.
SERVICE_NAME="greeks-service"
SOURCE_DIR="greeks_service"
BASEDPYRIGHT_MAX_ERRORS=0  # ratchet: 0 strict errors enforced; raised from no-ceiling (2026-06-15)
MIN_COVERAGE=70
RUN_INTEGRATION=false
PYTEST_WORKERS=${PYTEST_WORKERS:-2}
PYRIGHT_TIMEOUT=${PYRIGHT_TIMEOUT:-240}
MAX_DURATION=${MAX_DURATION:-600}
LOCAL_DEPS=()
WORKSPACE_ROOT="$(cd "$(git rev-parse --show-toplevel)/.." && pwd)"
# PYSEC-2026-161: starlette <1.0.1 — UTL pins starlette<1.0.0; upgrade blocked upstream
PIP_AUDIT_EXTRA_ARGS="--ignore-vuln PYSEC-2026-161"
# Broad except Exception: intentional resilience boundaries — see QUALITY_GATE_BYPASS_AUDIT.md §1.1
BE_EXCLUDE_GLOBS=(
    "greeks_service/inputs/mark_update_sub.py"
    "greeks_service/inputs/instrument_reader.py"
    "greeks_service/handlers/mark_update_handler.py"
    "greeks_service/outputs/pricing_ledger_writer.py"
    "greeks_service/batch/backfill.py"
)
# CODEX_MAX_VIOLATIONS pinned 2026-06-11 per plans/active/codex_violations_ratchet_to_five_2026_06_10.md (census-honest: 0 current violations; ratchet-down only).
CODEX_MAX_VIOLATIONS=0
source "${WORKSPACE_ROOT}/unified-trading-pm/scripts/quality-gates-base/base-service.sh"
