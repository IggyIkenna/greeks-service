"""Black-Scholes Greek computation kernel.

Implements the `GreekKernel` protocol for vanilla European options using
the classic Black-Scholes-Merton model.

All arithmetic uses `Decimal` to avoid float drift in ledger rows.
The module is a pure-function library — no I/O, no side effects, no globals.

Extensibility: alternative models (SABR, SVI, local-vol, numerical greeks)
MUST implement the `GreekKernel` protocol to stay drop-in compatible with
the greeks-service dispatch layer.

References:
  Hull, "Options, Futures, and Other Derivatives" § 19 (BSM formulas).
  Wilmott, "The Mathematics of Financial Derivatives" § 3 (put-call parity,
  early-exercise approximations).

SSOT: codex/04-architecture/greeks-service-overview.md § "Black-Scholes kernel".
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable


@runtime_checkable
class GreekKernel(Protocol):
    """Protocol that every greek-computation kernel must satisfy."""

    def compute(
        self,
        *,
        spot: Decimal,
        strike: Decimal,
        time_to_expiry: Decimal,
        risk_free_rate: Decimal,
        volatility: Decimal,
        right: str,
        dividend_yield: Decimal = Decimal(0),
    ) -> GreekResult:
        """Return all Greeks for a single option.

        Args:
            spot: Current underlying price.
            strike: Option strike price.
            time_to_expiry: Time to expiry in years (must be > 0).
            risk_free_rate: Continuously-compounded risk-free rate (annualised).
            volatility: Implied volatility (annualised, e.g. 0.20 = 20%).
            right: ``"CALL"`` or ``"PUT"`` (case-insensitive).
            dividend_yield: Continuous dividend yield (annualised; 0 for non-dividend).

        Returns:
            GreekResult with first-order (Δ/Θ/Vega/ρ) and second-order (Γ/vanna/volga) Greeks.
            Returns ``GreekResult.zero()`` for invalid / degenerate inputs (zero
            vol, zero time, etc.) — never raises from numerical degeneracies.
        """
        ...


class GreekResult:
    """Immutable container for BSM Greeks (first- and second-order).

    Fields:
        delta:  ∂V/∂S (per share)
        gamma:  ∂²V/∂S²
        theta:  ∂V/∂t per calendar day
        vega:   ∂V/∂σ per 1% move in implied vol
        rho:    ∂V/∂r per 1% move in risk-free rate
        vanna:  ∂Δ/∂σ (same for call and put; raw, per unit of fractional vol)
        volga:  ∂vega/∂σ (per-1%-vol vega sensitivity per unit of fractional vol)
    """

    __slots__ = ("delta", "gamma", "theta", "vega", "rho", "vanna", "volga")

    def __init__(
        self,
        *,
        delta: Decimal,
        gamma: Decimal,
        theta: Decimal,
        vega: Decimal,
        rho: Decimal,
        vanna: Decimal,
        volga: Decimal,
    ) -> None:
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.vega = vega
        self.rho = rho
        self.vanna = vanna
        self.volga = volga

    @classmethod
    def zero(cls) -> GreekResult:
        z = Decimal(0)
        return cls(delta=z, gamma=z, theta=z, vega=z, rho=z, vanna=z, volga=z)

    def __repr__(self) -> str:
        return (
            f"GreekResult(delta={self.delta}, gamma={self.gamma}, theta={self.theta}, "
            f"vega={self.vega}, rho={self.rho}, vanna={self.vanna}, volga={self.volga})"
        )


# ── Internal helpers ─────────────────────────────────────────────────────────

# Pre-computed constant: sqrt(2π)
_SQRT2PI = Decimal("2.5066282746310002")
_TWO = Decimal(2)
_ONE = Decimal(1)
_ZERO = Decimal(0)
_365 = Decimal(365)


def _norm_pdf(x: Decimal) -> Decimal:
    """Standard normal PDF — Decimal arithmetic."""
    try:
        return (_ONE / _SQRT2PI) * Decimal(math.exp(float(-x * x / _TWO)))
    except (OverflowError, InvalidOperation):
        return _ZERO


def _norm_cdf(x: Decimal) -> Decimal:
    """Standard normal CDF via math.erfc (float-then-clamp).

    Accurate to ~15 decimal places; Decimal wrapping avoids subsequent float
    drift in downstream arithmetic.
    """
    try:
        val = 0.5 * math.erfc(-float(x) / math.sqrt(2))
        return Decimal(str(round(val, 15)))
    except (OverflowError, ValueError):
        return _ONE if x > _ZERO else _ZERO


def _d1_d2(
    spot: Decimal,
    strike: Decimal,
    time_to_expiry: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
    dividend_yield: Decimal,
) -> tuple[Decimal, Decimal]:
    """Compute d1 and d2 for the BSM model (Merton 1973 continuous-dividend form)."""
    sqrt_t = Decimal(math.sqrt(float(time_to_expiry)))
    vol_sqrt_t = volatility * sqrt_t
    ln_s_k = Decimal(math.log(float(spot / strike)))
    d1 = (ln_s_k + (risk_free_rate - dividend_yield + volatility * volatility / _TWO) * time_to_expiry) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    return d1, d2


def _delta_rho_theta(
    right: str,
    spot: Decimal,
    strike: Decimal,
    time_to_expiry: Decimal,
    risk_free_rate: Decimal,
    dividend_yield: Decimal,
    disc_q: Decimal,
    disc_r: Decimal,
    sqrt_t: Decimal,
    n_d1: Decimal,
    n_d2: Decimal,
    n_neg_d1: Decimal,
    n_neg_d2: Decimal,
    pdf_d1: Decimal,
    volatility: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (delta, rho, theta_raw) for a CALL or PUT."""
    common = -spot * disc_q * pdf_d1 * volatility / (_TWO * sqrt_t)
    if right == "CALL":
        delta = disc_q * n_d1
        rho = strike * time_to_expiry * disc_r * n_d2 / Decimal(100)
        theta_raw = common - risk_free_rate * strike * disc_r * n_d2 + dividend_yield * spot * disc_q * n_d1
    else:  # PUT
        delta = disc_q * (n_d1 - _ONE)
        rho = -strike * time_to_expiry * disc_r * n_neg_d2 / Decimal(100)
        theta_raw = common + risk_free_rate * strike * disc_r * n_neg_d2 - dividend_yield * spot * disc_q * n_neg_d1
    return delta, rho, theta_raw


# ── Black-Scholes kernel ──────────────────────────────────────────────────────


class BlackScholesKernel:
    """BSM European option Greeks for vanilla CALL and PUT.

    Supports continuous dividend yield via the Merton (1973) generalisation.
    American options use the same formula with a note that early-exercise
    premium is not modelled (suitable for index options; use a numerical
    method for equity options near ex-dividend dates).
    """

    def compute(
        self,
        *,
        spot: Decimal,
        strike: Decimal,
        time_to_expiry: Decimal,
        risk_free_rate: Decimal,
        volatility: Decimal,
        right: str,
        dividend_yield: Decimal = _ZERO,
    ) -> GreekResult:
        """Return BSM Greeks for a single European option.

        Degenerate inputs (zero vol, zero time, zero spot) return
        ``GreekResult.zero()`` — never raises.
        """
        try:
            return self._compute_safe(
                spot=spot,
                strike=strike,
                time_to_expiry=time_to_expiry,
                risk_free_rate=risk_free_rate,
                volatility=volatility,
                right=right.upper(),
                dividend_yield=dividend_yield,
            )
        except (InvalidOperation, ZeroDivisionError, ValueError, OverflowError):
            return GreekResult.zero()

    def _compute_safe(
        self,
        *,
        spot: Decimal,
        strike: Decimal,
        time_to_expiry: Decimal,
        risk_free_rate: Decimal,
        volatility: Decimal,
        right: str,
        dividend_yield: Decimal,
    ) -> GreekResult:
        if spot <= _ZERO or strike <= _ZERO or time_to_expiry <= _ZERO or volatility <= _ZERO:
            return GreekResult.zero()

        d1, d2 = _d1_d2(spot, strike, time_to_expiry, risk_free_rate, volatility, dividend_yield)
        disc_q = Decimal(math.exp(-float(dividend_yield * time_to_expiry)))
        disc_r = Decimal(math.exp(-float(risk_free_rate * time_to_expiry)))
        sqrt_t = Decimal(math.sqrt(float(time_to_expiry)))
        n_d1, n_d2 = _norm_cdf(d1), _norm_cdf(d2)
        n_neg_d1, n_neg_d2 = _norm_cdf(-d1), _norm_cdf(-d2)
        pdf_d1 = _norm_pdf(d1)

        delta, rho, theta_raw = _delta_rho_theta(
            right,
            spot,
            strike,
            time_to_expiry,
            risk_free_rate,
            dividend_yield,
            disc_q,
            disc_r,
            sqrt_t,
            n_d1,
            n_d2,
            n_neg_d1,
            n_neg_d2,
            pdf_d1,
            volatility,
        )
        gamma = disc_q * pdf_d1 / (spot * volatility * sqrt_t)
        # Theta per calendar day (divide annual theta by 365)
        theta = theta_raw / _365
        # Vega per 1% move in vol (divide by 100)
        vega = spot * disc_q * pdf_d1 * sqrt_t / Decimal(100)
        # Vanna: ∂Δ/∂σ = -disc_q * N'(d1) * d2 / σ  (identical for call and put)
        vanna = -disc_q * pdf_d1 * d2 / volatility
        # Volga (vomma): ∂vega/∂σ = vega * d1 * d2 / σ
        volga = vega * d1 * d2 / volatility
        return GreekResult(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho, vanna=vanna, volga=volga)


# ── Implied-volatility fitting ────────────────────────────────────────────────

# Bisection search bounds (annualised vol)
_IV_LOW = Decimal("0.001")  # 0.1% — below this BS price ≈ intrinsic
_IV_HIGH = Decimal("10.0")  # 1000% — pathological upper bound
_IV_MAX_ITER = 100
_IV_TOL = Decimal("1e-8")  # convergence tolerance on IV


def _bs_price(
    spot: Decimal,
    strike: Decimal,
    time_to_expiry: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
    right: str,
    dividend_yield: Decimal,
) -> Decimal:
    """Return the BSM option price for the given inputs.

    Used internally by the IV solver. Returns 0 for degenerate inputs.
    """
    if spot <= _ZERO or strike <= _ZERO or time_to_expiry <= _ZERO or volatility <= _ZERO:
        return _ZERO
    try:
        d1, d2 = _d1_d2(spot, strike, time_to_expiry, risk_free_rate, volatility, dividend_yield)
        disc_q = Decimal(math.exp(-float(dividend_yield * time_to_expiry)))
        disc_r = Decimal(math.exp(-float(risk_free_rate * time_to_expiry)))
        if right == "CALL":
            return spot * disc_q * _norm_cdf(d1) - strike * disc_r * _norm_cdf(d2)
        else:
            return strike * disc_r * _norm_cdf(-d2) - spot * disc_q * _norm_cdf(-d1)
    except (OverflowError, InvalidOperation, ZeroDivisionError, ValueError):
        return _ZERO


def implied_vol_from_price(
    *,
    mark_price: Decimal,
    spot: Decimal,
    strike: Decimal,
    time_to_expiry: Decimal,
    risk_free_rate: Decimal,
    right: str,
    dividend_yield: Decimal = _ZERO,
    max_iter: int = _IV_MAX_ITER,
    tol: Decimal = _IV_TOL,
) -> Decimal | None:
    """Infer implied volatility from an observed option mark price via bisection.

    Solves BSM_price(σ) = mark_price for σ (annualised IV).
    Returns None when:
    - Inputs are degenerate (mark_price ≤ 0, time_to_expiry ≤ 0, etc.)
    - mark_price is below the model's intrinsic value floor (mispriced or closed)
    - mark_price exceeds the model's upper bound (e.g. above spot for a call)
    - Convergence fails within max_iter iterations

    Args:
        mark_price: Observed market / mid price of the option.
        spot: Current underlying price.
        strike: Option strike price.
        time_to_expiry: Time to expiry in years (must be > 0).
        risk_free_rate: Continuously-compounded risk-free rate (annualised).
        right: ``"CALL"`` or ``"PUT"`` (case-insensitive).
        dividend_yield: Continuous dividend yield (annualised; default 0).
        max_iter: Maximum bisection iterations (default 100).
        tol: Convergence tolerance on IV (default 1e-8).

    Returns:
        Implied volatility as a Decimal (e.g. ``Decimal("0.72")`` ≈ 72% IV),
        or None if the price is outside the no-arbitrage bounds or convergence
        fails.
    """
    if mark_price <= _ZERO or spot <= _ZERO or strike <= _ZERO or time_to_expiry <= _ZERO:
        return None

    r = right.upper()
    q = dividend_yield

    # Check bounds: price must lie within [intrinsic, theoretical max]
    price_low = _bs_price(spot, strike, time_to_expiry, risk_free_rate, _IV_LOW, r, q)
    price_high = _bs_price(spot, strike, time_to_expiry, risk_free_rate, _IV_HIGH, r, q)

    if mark_price < price_low or mark_price > price_high:
        return None

    lo = _IV_LOW
    hi = _IV_HIGH
    for _ in range(max_iter):
        mid = (lo + hi) / _TWO
        price_mid = _bs_price(spot, strike, time_to_expiry, risk_free_rate, mid, r, q)
        diff = price_mid - mark_price
        if abs(diff) <= tol:
            return mid
        if diff < _ZERO:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            return (lo + hi) / _TWO

    return None  # did not converge
