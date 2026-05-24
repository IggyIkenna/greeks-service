"""Greeks computation kernels — Black-Scholes and extensibility protocol."""

from .black_scholes import BlackScholesKernel, GreekKernel, GreekResult, implied_vol_from_price

__all__ = ["BlackScholesKernel", "GreekKernel", "GreekResult", "implied_vol_from_price"]
