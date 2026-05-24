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
            GreekResult with all five first-order and second-order Greeks.
            Returns ``GreekResult.zero()`` for invalid / degenerate inputs (zero
            vol, zero time, etc.) — never raises from numerical degeneracies.
        """
        ...


class GreekResult:
    """Immutable container for the five primary BSM Greeks."""

    __slots__ = ("delta", "gamma", "theta", "vega", "rho")

    def __init__(
        self,
        *,
        delta: Decimal,
        gamma: Decimal,
        theta: Decimal,
        vega: Decimal,
        rho: Decimal,
    ) -> None:
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.vega = vega
        self.rho = rho

    @classmethod
    def zero(cls) -> GreekResult:
        z = Decimal(0)
        return cls(delta=z, gamma=z, theta=z, vega=z, rho=z)

    def __repr__(self) -> str:
        return (
            f"GreekResult(delta={self.delta}, gamma={self.gamma}, theta={self.theta}, vega={self.vega}, rho={self.rho})"
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

        n_d1 = _norm_cdf(d1)
        n_d2 = _norm_cdf(d2)
        n_neg_d1 = _norm_cdf(-d1)
        n_neg_d2 = _norm_cdf(-d2)
        pdf_d1 = _norm_pdf(d1)
        sqrt_t = Decimal(math.sqrt(float(time_to_expiry)))

        if right == "CALL":
            delta = disc_q * n_d1
            rho = strike * time_to_expiry * disc_r * n_d2 / Decimal(100)
            theta_raw = (
                -spot * disc_q * pdf_d1 * volatility / (_TWO * sqrt_t)
                - risk_free_rate * strike * disc_r * n_d2
                + dividend_yield * spot * disc_q * n_d1
            )
        else:  # PUT
            delta = disc_q * (n_d1 - _ONE)
            rho = -strike * time_to_expiry * disc_r * n_neg_d2 / Decimal(100)
            theta_raw = (
                -spot * disc_q * pdf_d1 * volatility / (_TWO * sqrt_t)
                + risk_free_rate * strike * disc_r * n_neg_d2
                - dividend_yield * spot * disc_q * n_neg_d1
            )

        gamma = disc_q * pdf_d1 / (spot * volatility * sqrt_t)
        # Theta per calendar day (divide annual theta by 365)
        theta = theta_raw / _365
        # Vega per 1% move in vol (divide by 100)
        vega = spot * disc_q * pdf_d1 * sqrt_t / Decimal(100)

        return GreekResult(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)
