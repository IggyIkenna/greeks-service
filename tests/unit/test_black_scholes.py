"""Unit tests for the Black-Scholes greek computation kernel.

Covers:
  1. Protocol conformance — BlackScholesKernel satisfies GreekKernel
  2. Degenerate inputs — zero vol/time/spot/strike all return GreekResult.zero()
  3. ATM CALL — delta ≈ 0.5+, gamma > 0, theta < 0, vega > 0, rho > 0
  4. ATM PUT  — delta ≈ -0.5+, gamma > 0, theta < 0, vega > 0, rho < 0
  5. Greek sign constraints across the whole input space
  6. Call/put gamma & vega symmetry — identical by BSM formula
  7. Delta put-call parity — delta_call - delta_put == e^(-q*T)
  8. Deep ITM/OTM delta bounds
  9. Dividend yield effects on delta
  10. Case-insensitive right parameter ("call" / "CALL" / "Call")
  11. GreekResult.zero() classmethod
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from greeks_service.kernels.black_scholes import (
    BlackScholesKernel,
    GreekKernel,
    GreekResult,
    implied_vol_from_price,
)

pytestmark = pytest.mark.unit

# ── Shared fixtures ───────────────────────────────────────────────────────────

# ATM parameters: S=K=100, T=1y, r=5%, vol=20%, q=0
_S = Decimal("100")
_K = Decimal("100")
_T = Decimal("1")
_R = Decimal("0.05")
_V = Decimal("0.20")
_Q = Decimal("0")

_kernel = BlackScholesKernel()

_TOL = 1e-4  # tolerance for float comparisons after Decimal→float


def _call(**overrides: Decimal) -> GreekResult:
    params = dict(
        spot=_S, strike=_K, time_to_expiry=_T, risk_free_rate=_R, volatility=_V, right="CALL", dividend_yield=_Q
    )
    params.update(overrides)  # type: ignore[arg-type]
    return _kernel.compute(**params)  # type: ignore[arg-type]


def _put(**overrides: Decimal) -> GreekResult:
    params = dict(
        spot=_S, strike=_K, time_to_expiry=_T, risk_free_rate=_R, volatility=_V, right="PUT", dividend_yield=_Q
    )
    params.update(overrides)  # type: ignore[arg-type]
    return _kernel.compute(**params)  # type: ignore[arg-type]


# ── 1. Protocol conformance ───────────────────────────────────────────────────


class TestProtocol:
    def test_isinstance_greek_kernel(self) -> None:
        assert isinstance(_kernel, GreekKernel)

    def test_greek_result_has_five_slots(self) -> None:
        r = _call()
        assert hasattr(r, "delta")
        assert hasattr(r, "gamma")
        assert hasattr(r, "theta")
        assert hasattr(r, "vega")
        assert hasattr(r, "rho")

    def test_all_fields_are_decimal(self) -> None:
        r = _call()
        assert isinstance(r.delta, Decimal)
        assert isinstance(r.gamma, Decimal)
        assert isinstance(r.theta, Decimal)
        assert isinstance(r.vega, Decimal)
        assert isinstance(r.rho, Decimal)


# ── 2. Degenerate inputs ─────────────────────────────────────────────────────


class TestDegenerateInputs:
    def test_zero_volatility_returns_zero(self) -> None:
        r = _call(volatility=Decimal("0"))
        assert r == GreekResult.zero() or _is_zero_result(r)

    def test_zero_time_to_expiry_returns_zero(self) -> None:
        r = _call(time_to_expiry=Decimal("0"))
        assert _is_zero_result(r)

    def test_zero_spot_returns_zero(self) -> None:
        r = _call(spot=Decimal("0"))
        assert _is_zero_result(r)

    def test_zero_strike_returns_zero(self) -> None:
        r = _call(strike=Decimal("0"))
        assert _is_zero_result(r)

    def test_negative_spot_returns_zero(self) -> None:
        r = _call(spot=Decimal("-50"))
        assert _is_zero_result(r)

    def test_negative_volatility_returns_zero(self) -> None:
        r = _call(volatility=Decimal("-0.2"))
        assert _is_zero_result(r)

    def test_very_large_spot_does_not_raise(self) -> None:
        r = _call(spot=Decimal("1e9"))
        assert isinstance(r, GreekResult)

    def test_very_small_time_does_not_raise(self) -> None:
        r = _call(time_to_expiry=Decimal("1e-10"))
        assert isinstance(r, GreekResult)


def _is_zero_result(r: GreekResult) -> bool:
    z = Decimal(0)
    return r.delta == z and r.gamma == z and r.theta == z and r.vega == z and r.rho == z


# ── 3. ATM CALL — value and sign checks ──────────────────────────────────────


class TestAtmCall:
    def setup_method(self) -> None:
        self.r = _call()

    def test_delta_between_zero_and_one(self) -> None:
        assert Decimal(0) < self.r.delta < Decimal(1)

    def test_delta_above_half(self) -> None:
        # ATM call delta > 0.5 when r > 0 (forward > spot)
        assert float(self.r.delta) > 0.5

    def test_gamma_positive(self) -> None:
        assert self.r.gamma > Decimal(0)

    def test_theta_negative(self) -> None:
        assert self.r.theta < Decimal(0)

    def test_vega_positive(self) -> None:
        assert self.r.vega > Decimal(0)

    def test_rho_positive_for_positive_rate(self) -> None:
        assert self.r.rho > Decimal(0)

    def test_delta_approx(self) -> None:
        # N(d1) with d1≈0.35 → ~0.637
        assert abs(float(self.r.delta) - 0.637) < 0.005

    def test_gamma_approx(self) -> None:
        # n(d1)/(S*vol*sqrt(T)) ≈ 0.3752/20 ≈ 0.01876
        assert abs(float(self.r.gamma) - 0.01876) < 0.0005

    def test_vega_approx(self) -> None:
        # S*n(d1)*sqrt(T)/100 ≈ 100*0.3752*1/100 ≈ 0.3752
        assert abs(float(self.r.vega) - 0.3752) < 0.005

    def test_rho_approx(self) -> None:
        # K*T*disc_r*N(d2)/100 ≈ 100*1*0.9512*0.5596/100 ≈ 0.532
        assert abs(float(self.r.rho) - 0.532) < 0.01


# ── 4. ATM PUT — value and sign checks ───────────────────────────────────────


class TestAtmPut:
    def setup_method(self) -> None:
        self.r = _put()

    def test_delta_between_minus_one_and_zero(self) -> None:
        assert Decimal(-1) < self.r.delta < Decimal(0)

    def test_delta_above_minus_half(self) -> None:
        # ATM put delta > -0.5 when r > 0
        assert float(self.r.delta) > -0.5

    def test_gamma_positive(self) -> None:
        assert self.r.gamma > Decimal(0)

    def test_theta_negative(self) -> None:
        assert self.r.theta < Decimal(0)

    def test_vega_positive(self) -> None:
        assert self.r.vega > Decimal(0)

    def test_rho_negative_for_positive_rate(self) -> None:
        assert self.r.rho < Decimal(0)

    def test_delta_approx(self) -> None:
        # N(d1) - 1 ≈ 0.637 - 1 = -0.363
        assert abs(float(self.r.delta) - (-0.363)) < 0.005


# ── 5. Sign constraints across strike space ───────────────────────────────────


class TestSignConstraints:
    @pytest.mark.parametrize("strike", ["50", "80", "100", "120", "150"])
    def test_gamma_always_positive(self, strike: str) -> None:
        r = _call(strike=Decimal(strike))
        assert r.gamma >= Decimal(0)

    @pytest.mark.parametrize("strike", ["50", "80", "100", "120", "150"])
    def test_vega_always_positive(self, strike: str) -> None:
        r = _call(strike=Decimal(strike))
        assert r.vega >= Decimal(0)

    @pytest.mark.parametrize("strike", ["50", "80", "100", "120", "150"])
    def test_call_delta_always_in_zero_one(self, strike: str) -> None:
        r = _call(strike=Decimal(strike))
        assert Decimal(0) <= r.delta <= Decimal(1)

    @pytest.mark.parametrize("strike", ["50", "80", "100", "120", "150"])
    def test_put_delta_always_in_minus_one_zero(self, strike: str) -> None:
        r = _put(strike=Decimal(strike))
        assert Decimal(-1) <= r.delta <= Decimal(0)


# ── 6. Gamma & vega symmetry between call and put ────────────────────────────


class TestCallPutSymmetry:
    def test_gamma_equal_for_call_and_put(self) -> None:
        rc = _call()
        rp = _put()
        assert abs(float(rc.gamma) - float(rp.gamma)) < _TOL

    def test_vega_equal_for_call_and_put(self) -> None:
        rc = _call()
        rp = _put()
        assert abs(float(rc.vega) - float(rp.vega)) < _TOL

    @pytest.mark.parametrize("strike", ["70", "100", "130"])
    def test_gamma_symmetry_across_strikes(self, strike: str) -> None:
        k = Decimal(strike)
        rc = _call(strike=k)
        rp = _put(strike=k)
        assert abs(float(rc.gamma) - float(rp.gamma)) < _TOL

    @pytest.mark.parametrize("strike", ["70", "100", "130"])
    def test_vega_symmetry_across_strikes(self, strike: str) -> None:
        k = Decimal(strike)
        rc = _call(strike=k)
        rp = _put(strike=k)
        assert abs(float(rc.vega) - float(rp.vega)) < _TOL


# ── 7. Delta put-call parity ──────────────────────────────────────────────────


class TestDeltaParity:
    def test_delta_call_minus_put_equals_disc_q_no_dividend(self) -> None:
        # delta_call - delta_put = e^(-q*T) = 1 when q=0
        rc = _call()
        rp = _put()
        diff = float(rc.delta) - float(rp.delta)
        assert abs(diff - 1.0) < _TOL

    def test_delta_call_minus_put_with_dividend(self) -> None:
        q = Decimal("0.03")
        t = Decimal("2")
        expected = math.exp(-float(q) * float(t))
        rc = _call(dividend_yield=q, time_to_expiry=t)
        rp = _put(dividend_yield=q, time_to_expiry=t)
        diff = float(rc.delta) - float(rp.delta)
        assert abs(diff - expected) < _TOL

    @pytest.mark.parametrize("strike", ["70", "100", "130"])
    def test_delta_parity_across_strikes(self, strike: str) -> None:
        k = Decimal(strike)
        rc = _call(strike=k)
        rp = _put(strike=k)
        diff = float(rc.delta) - float(rp.delta)
        assert abs(diff - 1.0) < _TOL


# ── 8. Deep ITM / OTM delta bounds ───────────────────────────────────────────


class TestItmOtmBounds:
    def test_deep_itm_call_delta_near_one(self) -> None:
        # S=200, K=100 — very deep ITM call
        r = _call(spot=Decimal("200"))
        assert float(r.delta) > 0.95

    def test_deep_otm_call_delta_near_zero(self) -> None:
        # S=50, K=100 — very deep OTM call
        r = _call(spot=Decimal("50"))
        assert float(r.delta) < 0.05

    def test_deep_itm_put_delta_near_minus_one(self) -> None:
        # S=50, K=100 — very deep ITM put
        r = _put(spot=Decimal("50"))
        assert float(r.delta) < -0.95

    def test_deep_otm_put_delta_near_zero(self) -> None:
        # S=200, K=100 — very deep OTM put
        r = _put(spot=Decimal("200"))
        assert float(r.delta) > -0.05


# ── 9. Dividend yield effects ─────────────────────────────────────────────────


class TestDividendYield:
    def test_higher_dividend_reduces_call_delta(self) -> None:
        r0 = _call(dividend_yield=Decimal("0"))
        r1 = _call(dividend_yield=Decimal("0.05"))
        assert float(r1.delta) < float(r0.delta)

    def test_higher_dividend_lowers_put_delta(self) -> None:
        r0 = _put(dividend_yield=Decimal("0"))
        r1 = _put(dividend_yield=Decimal("0.05"))
        # put delta is negative; higher q reduces d1 → N(d1) smaller → delta more negative
        assert float(r1.delta) < float(r0.delta)

    def test_zero_dividend_explicit_same_as_default(self) -> None:
        r_default = _kernel.compute(
            spot=_S, strike=_K, time_to_expiry=_T, risk_free_rate=_R, volatility=_V, right="CALL"
        )
        r_explicit = _call(dividend_yield=Decimal("0"))
        assert abs(float(r_default.delta) - float(r_explicit.delta)) < _TOL


# ── 10. Case-insensitive right parameter ──────────────────────────────────────


class TestRightCaseInsensitive:
    def test_lowercase_call_same_as_uppercase(self) -> None:
        r_upper = _kernel.compute(spot=_S, strike=_K, time_to_expiry=_T, risk_free_rate=_R, volatility=_V, right="CALL")
        r_lower = _kernel.compute(spot=_S, strike=_K, time_to_expiry=_T, risk_free_rate=_R, volatility=_V, right="call")
        assert abs(float(r_upper.delta) - float(r_lower.delta)) < _TOL

    def test_mixed_case_put_same_as_uppercase(self) -> None:
        r_upper = _kernel.compute(spot=_S, strike=_K, time_to_expiry=_T, risk_free_rate=_R, volatility=_V, right="PUT")
        r_mixed = _kernel.compute(spot=_S, strike=_K, time_to_expiry=_T, risk_free_rate=_R, volatility=_V, right="Put")
        assert abs(float(r_upper.delta) - float(r_mixed.delta)) < _TOL


# ── 11. GreekResult helpers ───────────────────────────────────────────────────


class TestGreekResult:
    def test_zero_classmethod_returns_all_zeros(self) -> None:
        r = GreekResult.zero()
        z = Decimal(0)
        assert r.delta == z
        assert r.gamma == z
        assert r.theta == z
        assert r.vega == z
        assert r.rho == z

    def test_repr_contains_all_field_names(self) -> None:
        r = _call()
        s = repr(r)
        assert "delta=" in s
        assert "gamma=" in s
        assert "theta=" in s
        assert "vega=" in s
        assert "rho=" in s


# ── 12. Implied-volatility fitting ───────────────────────────────────────────


class TestImpliedVolFromPrice:
    """implied_vol_from_price: round-trips and edge cases."""

    _IV_TOL = 1e-5  # tolerance for IV round-trip (0.001%)

    def _atm_call_price(self, vol: Decimal) -> Decimal:
        """BS price for ATM call: S=K=100, T=1y, r=5%, q=0."""
        from greeks_service.kernels.black_scholes import _bs_price

        return _bs_price(_S, _K, _T, _R, vol, "CALL", Decimal(0))

    def test_round_trip_atm_call(self) -> None:
        target_iv = Decimal("0.20")
        mark = self._atm_call_price(target_iv)
        fitted = implied_vol_from_price(
            mark_price=mark,
            spot=_S,
            strike=_K,
            time_to_expiry=_T,
            risk_free_rate=_R,
            right="CALL",
        )
        assert fitted is not None
        assert abs(float(fitted) - float(target_iv)) < self._IV_TOL, f"fitted={fitted}"

    def test_round_trip_atm_put(self) -> None:
        from greeks_service.kernels.black_scholes import _bs_price

        target_iv = Decimal("0.35")
        mark = _bs_price(_S, _K, _T, _R, target_iv, "PUT", Decimal(0))
        fitted = implied_vol_from_price(
            mark_price=mark,
            spot=_S,
            strike=_K,
            time_to_expiry=_T,
            risk_free_rate=_R,
            right="PUT",
        )
        assert fitted is not None
        assert abs(float(fitted) - float(target_iv)) < self._IV_TOL, f"fitted={fitted}"

    def test_high_vol_round_trip(self) -> None:
        target_iv = Decimal("0.80")
        mark = self._atm_call_price(target_iv)
        fitted = implied_vol_from_price(
            mark_price=mark,
            spot=_S,
            strike=_K,
            time_to_expiry=_T,
            risk_free_rate=_R,
            right="CALL",
        )
        assert fitted is not None
        assert abs(float(fitted) - float(target_iv)) < self._IV_TOL

    def test_low_vol_round_trip(self) -> None:
        target_iv = Decimal("0.05")
        mark = self._atm_call_price(target_iv)
        fitted = implied_vol_from_price(
            mark_price=mark,
            spot=_S,
            strike=_K,
            time_to_expiry=_T,
            risk_free_rate=_R,
            right="CALL",
        )
        assert fitted is not None
        assert abs(float(fitted) - float(target_iv)) < self._IV_TOL

    def test_with_dividend_yield_round_trip(self) -> None:
        from greeks_service.kernels.black_scholes import _bs_price

        target_iv = Decimal("0.25")
        q = Decimal("0.015")
        mark = _bs_price(_S, _K, _T, _R, target_iv, "CALL", q)
        fitted = implied_vol_from_price(
            mark_price=mark,
            spot=_S,
            strike=_K,
            time_to_expiry=_T,
            risk_free_rate=_R,
            right="CALL",
            dividend_yield=q,
        )
        assert fitted is not None
        assert abs(float(fitted) - float(target_iv)) < self._IV_TOL

    def test_zero_mark_price_returns_none(self) -> None:
        assert implied_vol_from_price(
            mark_price=Decimal(0),
            spot=_S,
            strike=_K,
            time_to_expiry=_T,
            risk_free_rate=_R,
            right="CALL",
        ) is None

    def test_expired_option_returns_none(self) -> None:
        assert implied_vol_from_price(
            mark_price=Decimal("10"),
            spot=_S,
            strike=_K,
            time_to_expiry=Decimal(0),
            risk_free_rate=_R,
            right="CALL",
        ) is None

    def test_price_below_intrinsic_returns_none(self) -> None:
        # A deep ITM call at S=200, K=100, T=1y — intrinsic is ~100; price=1 is below bound
        assert implied_vol_from_price(
            mark_price=Decimal("1"),
            spot=Decimal("200"),
            strike=Decimal("100"),
            time_to_expiry=_T,
            risk_free_rate=_R,
            right="CALL",
        ) is None

    def test_case_insensitive_right(self) -> None:
        target_iv = Decimal("0.30")
        mark = self._atm_call_price(target_iv)
        fitted_lower = implied_vol_from_price(
            mark_price=mark, spot=_S, strike=_K, time_to_expiry=_T,
            risk_free_rate=_R, right="call",
        )
        fitted_upper = implied_vol_from_price(
            mark_price=mark, spot=_S, strike=_K, time_to_expiry=_T,
            risk_free_rate=_R, right="CALL",
        )
        assert fitted_lower is not None and fitted_upper is not None
        assert abs(float(fitted_lower) - float(fitted_upper)) < 1e-10
