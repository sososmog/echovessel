"""AnthropicProvider tier-resolution and error-classification tests.

These tests never talk to a real Anthropic endpoint. The SDK client is
constructed lazily, so we only exercise the resolution logic and the
`_classify_anthropic_error` helper.
"""

from __future__ import annotations

import pytest

from echovessel.runtime.llm.anthropic import (
    AnthropicProvider,
    _classify_anthropic_error,
)
from echovessel.runtime.llm.base import LLMTier
from echovessel.runtime.llm.errors import (
    LLMBudgetError,
    LLMPermanentError,
    LLMTransientError,
)


def test_default_tier_mapping_when_no_overrides():
    p = AnthropicProvider(api_key="fake")
    assert p.provider_name == "anthropic"
    assert p.model_for(LLMTier.SMALL) == "claude-haiku-4-5"
    assert p.model_for(LLMTier.MEDIUM) == "claude-sonnet-4-6"
    assert p.model_for(LLMTier.LARGE) == "claude-opus-4-6"


def test_pinned_model_overrides_all_tiers():
    p = AnthropicProvider(api_key="fake", pinned_model="claude-opus-4-6")
    for tier in LLMTier:
        assert p.model_for(tier) == "claude-opus-4-6"


def test_tier_models_override_defaults():
    p = AnthropicProvider(
        api_key="fake",
        tier_models={"small": "claude-haiku-4-5", "medium": "claude-sonnet-4-6", "large": "claude-opus-4-6"},
    )
    assert p.model_for(LLMTier.SMALL) == "claude-haiku-4-5"


def test_tier_models_partial_with_official_fills_defaults():
    p = AnthropicProvider(api_key="fake", tier_models={"large": "claude-opus-4-6"})
    assert p.model_for(LLMTier.LARGE) == "claude-opus-4-6"
    # other tiers still get defaults because base_url is official
    assert p.model_for(LLMTier.SMALL) == "claude-haiku-4-5"


def test_custom_base_url_requires_model_or_tier_models():
    with pytest.raises(ValueError, match="cannot resolve model for tier"):
        AnthropicProvider(
            api_key="fake",
            base_url="https://some-proxy.example.com/v1",
        )


def test_custom_base_url_with_pinned_model_succeeds():
    p = AnthropicProvider(
        api_key="fake",
        base_url="https://some-proxy.example.com/v1",
        pinned_model="my-custom-model",
    )
    assert p.model_for(LLMTier.SMALL) == "my-custom-model"
    assert p.base_url == "https://some-proxy.example.com/v1"


def test_unknown_tier_key_raises():
    with pytest.raises(ValueError, match="Unknown tier"):
        AnthropicProvider(api_key="fake", tier_models={"huge": "x"})


# ---- error classification --------------------------------------------------


class _FakeError(Exception):
    def __init__(self, msg, status_code=None):
        super().__init__(msg)
        self.status_code = status_code


def test_classify_5xx_as_transient():
    out = _classify_anthropic_error(_FakeError("boom", 503))
    assert isinstance(out, LLMTransientError)


def test_classify_429_as_transient():
    out = _classify_anthropic_error(_FakeError("rate", 429))
    assert isinstance(out, LLMTransientError)


def test_classify_401_as_permanent():
    out = _classify_anthropic_error(_FakeError("unauth", 401))
    assert isinstance(out, LLMPermanentError)
    assert not isinstance(out, LLMTransientError)


def test_classify_402_as_budget():
    out = _classify_anthropic_error(_FakeError("paid", 402))
    assert isinstance(out, LLMBudgetError)


class _ConnectionTimeoutError(Exception):
    pass


def test_classify_unknown_connection_as_transient():
    out = _classify_anthropic_error(_ConnectionTimeoutError("oops"))
    assert isinstance(out, LLMTransientError)
