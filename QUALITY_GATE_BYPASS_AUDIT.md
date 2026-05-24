# Quality Gate Bypass Audit

## §1.1 Broad `except Exception:` Exclusions

The quality gate flags `except Exception:` in production code. The following files use broad
exception handling intentionally for infrastructure resilience — errors must be logged and
service must continue handling subsequent messages.

| File                                              | Lines                       | Reason                                                                                                                       |
| ------------------------------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `greeks_service/inputs/mark_update_sub.py`        | dispatch loop               | A bad Pub/Sub message must not abort delivery to subsequent messages; errors are logged and ack is withheld                  |
| `greeks_service/inputs/instrument_reader.py`      | `_fetch_http`               | IS HTTP failure must return None (instrument unknown), not crash the greeks compute loop                                     |
| `greeks_service/handlers/mark_update_handler.py`  | `_compute_greeks`, `handle` | Failed greeks compute for one instrument must not stop processing of the next instrument; errors logged                      |
| `greeks_service/outputs/pricing_ledger_writer.py` | `write`                     | GCS write failure is logged then re-raised to caller; broad catch added only to ensure structured logging before propagation |

**Config:** `BE_EXCLUDE_GLOBS` in `scripts/quality-gates.sh`

## §1.2 File Size Exceptions

None.

## §2 Ruff Exceptions

None.

## §3 Basedpyright Exceptions

None.
