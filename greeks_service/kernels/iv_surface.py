"""Implied-volatility surface assembler.

Builds an IV surface — IV organised by (strike / moneyness) × (expiry / tenor) —
from an options chain snapshot (the venue-published mark IV per leg, plus the
underlying mark). Where a leg has no published mark IV but does have a mark
price, the IV is fitted in-house via the Black-Scholes solver
(``implied_vol_from_price``) — never invented.

Pure-function library: no I/O, no globals, no peer-service imports. Inputs are
plain values (an ``OptionQuote`` per leg), so it composes with the
instruments-service ``CanonicalOptionsChain`` at the call site without importing
it (Layer-1.5 contract boundary). All datetimes are UTC. Arithmetic is
``Decimal`` for IV consistency with the BS kernel + ledger rows.

SSOT: codex/04-architecture/greeks-service-overview.md § "IV surface".

# SCHEMA_PROVENANCE_EXEMPT — OptionQuote/SurfacePoint/IVSurface are service-local
# in-memory computation containers for the IV-surface kernel (not wire-format /
# domain contracts crossing a service boundary), mirroring black_scholes.GreekResult.
# They are NOT general-purpose domain types, so they stay local rather than in UAC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from greeks_service.kernels.black_scholes import implied_vol_from_price

_ZERO = Decimal(0)
_SECONDS_PER_YEAR = Decimal(str(365.25 * 24 * 3600))


@dataclass(frozen=True)
class OptionQuote:
    """A single option leg's snapshot inputs for surface assembly.

    Exactly one IV source is required per leg: ``mark_iv`` (venue-published,
    annualised fractional) takes precedence; otherwise ``mark_price`` is used to
    fit IV via Black-Scholes. ``right`` is ``"CALL"`` / ``"PUT"`` (case-insensitive).
    """

    instrument_key: str
    strike: Decimal
    expiry: datetime
    right: str
    mark_iv: Decimal | None = None
    mark_price: Decimal | None = None


@dataclass(frozen=True)
class SurfacePoint:
    """One (strike × expiry) node on the IV surface."""

    instrument_key: str
    strike: Decimal
    expiry: datetime
    right: str
    moneyness: Decimal  # strike / underlying_mark
    tenor_years: Decimal  # (expiry - as_of) in years
    implied_vol: Decimal  # annualised, fractional
    iv_source: str  # "mark_iv" | "fitted"


@dataclass
class IVSurface:
    """Assembled IV surface for one underlying at one snapshot time.

    ``points`` is the flat node list; ``by_expiry`` / ``by_strike`` index it for
    term-structure / skew reads. Empty surface = no leg had a usable IV (honest
    absence — never a placeholder node).
    """

    underlying: str
    underlying_mark: Decimal
    as_of: datetime
    points: list[SurfacePoint] = field(default_factory=list)
    by_expiry: dict[datetime, list[SurfacePoint]] = field(default_factory=dict)
    by_strike: dict[Decimal, list[SurfacePoint]] = field(default_factory=dict)


def _tenor_years(as_of: datetime, expiry: datetime) -> Decimal:
    """Time to expiry in years (UTC). Clamped at 0 for expired legs."""
    seconds = Decimal(str((expiry - as_of).total_seconds()))
    return seconds / _SECONDS_PER_YEAR if seconds > _ZERO else _ZERO


def _resolve_iv(
    quote: OptionQuote,
    *,
    underlying_mark: Decimal,
    tenor_years: Decimal,
    risk_free_rate: Decimal,
    dividend_yield: Decimal,
) -> tuple[Decimal, str] | None:
    """Resolve a leg's IV: venue mark_iv if present + positive, else fit from mark_price.

    Returns ``(iv, source)`` or ``None`` when no usable IV exists (honest absence).
    """
    if quote.mark_iv is not None and quote.mark_iv > _ZERO:
        return quote.mark_iv, "mark_iv"
    if quote.mark_price is not None and tenor_years > _ZERO:
        fitted = implied_vol_from_price(
            mark_price=quote.mark_price,
            spot=underlying_mark,
            strike=quote.strike,
            time_to_expiry=tenor_years,
            risk_free_rate=risk_free_rate,
            right=quote.right,
            dividend_yield=dividend_yield,
        )
        if fitted is not None and fitted > _ZERO:
            return fitted, "fitted"
    return None


def assemble_iv_surface(
    *,
    underlying: str,
    underlying_mark: Decimal,
    quotes: list[OptionQuote],
    as_of: datetime | None = None,
    risk_free_rate: Decimal = Decimal("0.05"),
    dividend_yield: Decimal = _ZERO,
) -> IVSurface:
    """Assemble an IV surface from an option chain's leg quotes.

    Args:
        underlying: Underlying symbol (e.g. ``"BTC"``).
        underlying_mark: Current underlying mark/index price (must be > 0).
        quotes: One ``OptionQuote`` per option leg (call + put across strikes/expiries).
        as_of: Snapshot time (UTC); defaults to now.
        risk_free_rate: Continuously-compounded annualised rate for IV fitting.
        dividend_yield: Continuous dividend/carry yield for IV fitting.

    Returns:
        ``IVSurface`` with one ``SurfacePoint`` per leg that yielded a usable IV.
        Legs with neither a positive mark IV nor a fittable mark price are
        dropped (honest absence — no synthetic node).
    """
    moment = as_of or datetime.now(UTC)
    surface = IVSurface(underlying=underlying, underlying_mark=underlying_mark, as_of=moment)
    if underlying_mark <= _ZERO:
        return surface

    for quote in quotes:
        tenor = _tenor_years(moment, quote.expiry)
        resolved = _resolve_iv(
            quote,
            underlying_mark=underlying_mark,
            tenor_years=tenor,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
        )
        if resolved is None:
            continue
        iv, source = resolved
        point = SurfacePoint(
            instrument_key=quote.instrument_key,
            strike=quote.strike,
            expiry=quote.expiry,
            right=quote.right.upper(),
            moneyness=quote.strike / underlying_mark,
            tenor_years=tenor,
            implied_vol=iv,
            iv_source=source,
        )
        surface.points.append(point)
        surface.by_expiry.setdefault(quote.expiry, []).append(point)
        surface.by_strike.setdefault(quote.strike, []).append(point)

    surface.points.sort(key=lambda p: (p.expiry, p.strike, p.right))
    for nodes in surface.by_expiry.values():
        nodes.sort(key=lambda p: (p.strike, p.right))
    for nodes in surface.by_strike.values():
        nodes.sort(key=lambda p: (p.expiry, p.right))
    return surface
