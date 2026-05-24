#!/usr/bin/env bash
# Repo-specific settings only. Body: unified-trading-pm/scripts/quality-gates-base/base-service.sh
# SSOT: unified-trading-pm/codex/06-coding-standards/quality-gates-service-template.sh
#
# Phase 1 skeleton: minimal settings — extends as handlers / adapters / scripts land in
# subsequent phases of plans/active/global_ledger_pnl_attribution_migration_2026_06_01.md.
SERVICE_NAME="greeks-service"
SOURCE_DIR="greeks_service"
MIN_COVERAGE=70
RUN_INTEGRATION=false
PYTEST_WORKERS=${PYTEST_WORKERS:-2}
LOCAL_DEPS=()
WORKSPACE_ROOT="$(cd "$(git rev-parse --show-toplevel)/.." && pwd)"
# PYSEC-2026-161: starlette <1.0.1 — UTL pins starlette<1.0.0; upgrade blocked upstream
PIP_AUDIT_EXTRA_ARGS="--ignore-vuln PYSEC-2026-161"
source "${WORKSPACE_ROOT}/unified-trading-pm/scripts/quality-gates-base/base-service.sh"
