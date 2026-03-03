"""Rate-limiting helpers."""

import aiolimiter


def create_limiter(rate_limit: float, rate_period: float) -> aiolimiter.AsyncLimiter:
    """Create an AsyncLimiter, normalizing so max_rate >= 1.

    aiolimiter.AsyncLimiter requires max_rate >= 1 because acquire()
    requests 1 token by default. When rate_limit < 1, we scale both
    values to keep the same effective rate with max_rate = 1.
    """
    if rate_limit < 1.0:
        rate_period = rate_period / rate_limit
        rate_limit = 1.0
    return aiolimiter.AsyncLimiter(max_rate=rate_limit, time_period=rate_period)
