"""Error types the tool raises.

Each one carries a plain-language message, so the app (or the command line)
can show it to the user directly instead of a raw Python crash.
"""


class PortfolioToolError(Exception):
    """Base class for every error this tool raises on purpose."""


class PortfolioInputError(PortfolioToolError, ValueError):
    """The portfolio the user entered is not usable (bad tickers or weights)."""


class DataFetchError(PortfolioToolError):
    """Price or Treasury data could not be pulled from FMP."""


class InsufficientDataError(PortfolioToolError):
    """There is not enough price history to estimate risk and return."""


class OptimizationError(PortfolioToolError):
    """The math solver failed to find a portfolio."""
