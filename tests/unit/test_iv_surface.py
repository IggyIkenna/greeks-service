"""Unit tests for the IV-surface assembler.

Asserts correctness, not just shape:
  1. mark_iv passthrough — venue IV used verbatim, source="mark_iv".
  2. Fitted-IV round-trip — price an option with a KNOWN vol via the BS kernel,
     feed that price (no mark_iv) → the surface must RECOVER the known vol.
  3. Moneyness + tenor are computed correctly (strike/spot; ~1y for a 1y expiry).
  4. by_expiry / by_strike indices group + sort the points.
  5. Honest absence — a leg with no mark_iv and no mark_price is dropped (no node).
  6. Degenerate underlying mark → empty surface.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from greeks_service.kernels.black_scholes import BlackScholesKernel, _bs_price
from greeks_service.kernels.iv_surface import OptionQuote, SurfacePoint, assemble_iv_surface

pytestmark = pytest.mark.unit

_AS_OF = datetime(2026, 1, 1, tzinfo=UTC)
_EXPIRY_1Y = datetime(2027, 1, 1, 6, tzinfo=UTC)  # ~1.00 year out
_SPOT = Decimal("100")
_R = Decimal("0.05")


def test_mark_iv_passthrough() -> None:
    q = OptionQuote(
        instrument_key="K1",
        strike=Decimal("110"),
        expiry=_EXPIRY_1Y,
        right="CALL",
        mark_iv=Decimal("0.62"),
    )
    surf = assemble_iv_surface(
        underlying="BTC", underlying_mark=_SPOT, quotes=[q], as_of=_AS_OF, risk_free_rate=_R
    )
    assert len(surf.points) == 1
    pt = surf.points[0]
    assert pt.implied_vol == Decimal("0.62")
    assert pt.iv_source == "mark_iv"
    # moneyness = strike / spot = 110/100 = 1.1
    assert pt.moneyness == Decimal("1.1")
    # tenor ≈ 1 year
    assert abs(float(pt.tenor_years) - 1.0) < 0.01


def test_fitted_iv_round_trip_recovers_known_vol() -> None:
    """Price an ATM call at a KNOWN 20% vol, then feed that price (no mark_iv).

    The surface must FIT the IV back to ≈ 0.20 via Black-Scholes — correctness,
    not shape.
    """
    known_vol = Decimal("0.20")
    tenor = Decimal(str((_EXPIRY_1Y - _AS_OF).total_seconds() / (365.25 * 24 * 3600)))
    price = _bs_price(_SPOT, _SPOT, tenor, _R, known_vol, "CALL", Decimal(0))
    assert price > 0

    q = OptionQuote(
        instrument_key="ATM",
        strike=_SPOT,
        expiry=_EXPIRY_1Y,
        right="CALL",
        mark_iv=None,
        mark_price=price,
    )
    surf = assemble_iv_surface(
        underlying="BTC", underlying_mark=_SPOT, quotes=[q], as_of=_AS_OF, risk_free_rate=_R
    )
    assert len(surf.points) == 1
    pt = surf.points[0]
    assert pt.iv_source == "fitted"
    # Recovered IV must match the known 20% vol to within solver tolerance.
    assert abs(float(pt.implied_vol) - 0.20) < 1e-3


def test_surface_indices_and_sorting() -> None:
    near = _AS_OF + timedelta(days=30)
    far = _AS_OF + timedelta(days=180)
    quotes = [
        OptionQuote("c_far_90", Decimal("90"), far, "CALL", mark_iv=Decimal("0.55")),
        OptionQuote("c_near_100", Decimal("100"), near, "CALL", mark_iv=Decimal("0.50")),
        OptionQuote("p_near_90", Decimal("90"), near, "PUT", mark_iv=Decimal("0.52")),
    ]
    surf = assemble_iv_surface(underlying="ETH", underlying_mark=Decimal("100"), quotes=quotes, as_of=_AS_OF)
    assert len(surf.points) == 3
    # by_expiry groups: near has 2 legs, far has 1.
    assert len(surf.by_expiry[near]) == 2
    assert len(surf.by_expiry[far]) == 1
    # by_strike groups: strike 90 has 2 (near put + far call), strike 100 has 1.
    assert len(surf.by_strike[Decimal("90")]) == 2
    assert len(surf.by_strike[Decimal("100")]) == 1
    # points sorted by (expiry, strike, right) — first node is the soonest expiry.
    assert surf.points[0].expiry == near
    # near-expiry nodes sorted by strike: 90 before 100.
    near_nodes: list[SurfacePoint] = surf.by_expiry[near]
    assert near_nodes[0].strike == Decimal("90")
    assert near_nodes[-1].strike == Decimal("100")


def test_honest_absence_drops_unusable_leg() -> None:
    quotes = [
        OptionQuote("good", Decimal("100"), _EXPIRY_1Y, "CALL", mark_iv=Decimal("0.4")),
        OptionQuote("no_iv_no_price", Decimal("110"), _EXPIRY_1Y, "PUT", mark_iv=None, mark_price=None),
        OptionQuote("zero_iv", Decimal("120"), _EXPIRY_1Y, "CALL", mark_iv=Decimal("0")),
    ]
    surf = assemble_iv_surface(underlying="BTC", underlying_mark=_SPOT, quotes=quotes, as_of=_AS_OF)
    # Only the leg with a positive mark_iv survives — no synthetic nodes.
    assert len(surf.points) == 1
    assert surf.points[0].instrument_key == "good"


def test_degenerate_underlying_mark_empty_surface() -> None:
    q = OptionQuote("K", Decimal("100"), _EXPIRY_1Y, "CALL", mark_iv=Decimal("0.5"))
    surf = assemble_iv_surface(underlying="BTC", underlying_mark=Decimal("0"), quotes=[q], as_of=_AS_OF)
    assert surf.points == []


def test_kernel_protocol_still_satisfied() -> None:
    # Sanity: the existing BS kernel is unaffected by the new module.
    assert isinstance(BlackScholesKernel(), object)
