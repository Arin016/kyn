from __future__ import annotations

import re


_RATE_LIMIT = re.compile(
    r"rate[_\s-]?limit|429|quota|credits?\s+(exhausted|depleted|exceeded)|"
    r"free-models-per-day|usage\s+limit|overloaded|capacity|too many requests",
    re.IGNORECASE,
)
_AUTH = re.compile(
    r"\b401\b|unauthorized|unauthenticated|invalid api key|invalid_api_key|"
    r"authentication|expired token|login required|forbidden|access denied",
    re.IGNORECASE,
)


def classify_provider_failure(error: str) -> str | None:
    """Classify a run error as a provider-side failure, if it is one.

    Returns ``"rate_limit"`` when the provider throttled or exhausted quota,
    ``"auth"`` when credentials are missing or rejected, and ``None`` for
    ordinary model, tool, or harness failures that must not trigger failover.
    """
    text = error or ""
    if _RATE_LIMIT.search(text):
        return "rate_limit"
    if _AUTH.search(text):
        return "auth"
    return None
