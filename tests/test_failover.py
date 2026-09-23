from __future__ import annotations

from kyn.failover import classify_provider_failure


def test_rate_limit_variants_classify() -> None:
    assert classify_provider_failure("Rate limit exceeded: free-models-per-day") == "rate_limit"
    assert classify_provider_failure("429 too many requests") == "rate_limit"
    assert classify_provider_failure("quota exhausted for today") == "rate_limit"
    assert classify_provider_failure("APIError: overloaded") == "rate_limit"


def test_auth_variants_classify() -> None:
    assert classify_provider_failure("401 unauthorized") == "auth"
    assert classify_provider_failure("invalid api key") == "auth"
    assert classify_provider_failure("login required") == "auth"


def test_ordinary_failures_do_not_classify() -> None:
    assert classify_provider_failure("simulated turn failure") is None
    assert classify_provider_failure("model returned no actions") is None
    assert classify_provider_failure("") is None
    assert classify_provider_failure("Kiro ACP process is not running") is None
