# greeks-service

greeks-service is the dedicated workspace service that computes options greeks (delta, gamma,
vega, theta, rho) and carry-family rates (basis, funding, lending/staking APR) for every
position the workspace marks-to-market, and writes the results to the global `PricingLedger`
SSOT (`unified_api_contracts.canonical.crosscutting.ledger`).

It exists as a standalone service — separate from `market-tick-data-service` (which is
market-data-only) and from `strategy-service` (which consumes greeks rather than producing
them) — because greeks computation is a pure derivation step that fans in from MTDS mark
prices + instruments-service instrument metadata and fans out to the pricing ledger consumed
by strategy / execution / risk / pnl-attribution. Phase 1 of the
`global_ledger_pnl_attribution_migration_2026_06_01.md` migration plan stubs the service
skeleton; Phase 2+ wires the BlackScholesGreeksCalculator, carry-rate readers, batch/live
mode handlers, and PricingLedger writers.

> **CI note**: this repo's `main-backmerge-to-ldr.yml` was silently broken 2026-08-04 through
> 2026-08-05 (missing `notify-slack.yml`, fixed fleet-wide at
> `unified-trading-pm@11a9e776f`) — see
> `unified-trading-pm/plans/active/ci_pipeline_speed_and_cost_redesign_2026_08_05.md` for the
> live LDR→main promotion timing this change is exercising.
