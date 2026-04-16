"""OpenAICompatibleProvider tier-resolution and error-classification tests."""

from __future__ import annotations

import pytest

from echovessel.runtime.llm.base import LLMTier
from echovessel.runtime.llm.errors import (
    LLMBudgetError,
    LLMPermanentError,
    LLMTransientError,
)
from echovessel.runtime.llm.openai_compat import (
    OpenAICompatibleProvider,
    _classify_openai_error,
)


def test_official_defaults():
    p = OpenAICompatibleProvider(api_key="fake")
    assert p.provider_name == "openai_compat"
    assert p.model_for(LLMTier.SMALL) == "gpt-4o-mini"
    assert p.model_for(LLMTier.MEDIUM) == "gpt-4o"
    assert p.model_for(LLMTier.LARGE) == "gpt-4o"


def test_pinned_model_overrides_all_tiers():
    p = OpenAICompatibleProvider(api_key="fake", pinned_model="gpt-4o")
    for tier in LLMTier:
        assert p.model_for(tier) == "gpt-4o"


def test_explicit_openai_base_url_still_gets_defaults():
    p = OpenAICompatibleProvider(
        api_key="fake", base_url="https://api.openai.com/v1"
    )
    assert p.model_for(LLMTier.SMALL) == "gpt-4o-mini"


def test_custom_base_url_requires_model_or_tier_models():
    with pytest.raises(ValueError, match="cannot resolve model for tier"):
        OpenAICompatibleProvider(
            api_key=None,
            base_url="http://localhost:11434/v1",
        )


def test_ollama_with_explicit_tier_models_succeeds():
    p = OpenAICompatibleProvider(
        api_key=None,
        base_url="http://localhost:11434/v1",
        tier_models={"small": "llama3:8b", "medium": "llama3:70b", "large": "llama3:70b"},
    )
    assert p.model_for(LLMTier.SMALL) == "llama3:8b"
    assert p.model_for(LLMTier.LARGE) == "llama3:70b"


def test_openrouter_with_pinned_model_succeeds():
    p = OpenAICompatibleProvider(
        api_key="fake",
        base_url="https://openrouter.ai/api/v1",
        pinned_model="anthropic/claude-sonnet-4",
    )
    assert p.model_for(LLMTier.SMALL) == "anthropic/claude-sonnet-4"
    assert p.base_url == "https://openrouter.ai/api/v1"


# ---- error classification --------------------------------------------------


class _FakeError(Exception):
    def __init__(self, msg, status_code=None):
        super().__init__(msg)
        self.status_code = status_code


def test_classify_5xx_transient():
    assert isinstance(_classify_openai_error(_FakeError("", 502)), LLMTransientError)


def test_classify_401_permanent():
    assert isinstance(_classify_openai_error(_FakeError("", 401)), LLMPermanentError)


def test_classify_402_budget():
    assert isinstance(_classify_openai_error(_FakeError("", 402)), LLMBudgetError)


def test_classify_429_transient():
    assert isinstance(_classify_openai_error(_FakeError("", 429)), LLMTransientError)
