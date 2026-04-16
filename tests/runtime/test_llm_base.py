"""LLMProvider Protocol + LLMTier basic contract tests (PR 1)."""

from __future__ import annotations

import pytest

from echovessel.runtime.llm import (
    LLMBudgetError,
    LLMError,
    LLMPermanentError,
    LLMProvider,
    LLMTier,
    LLMTransientError,
    StubProvider,
)


def test_tier_values_are_stable_strings():
    # Downstream (EVAL harness, WEB) imports these literal values.
    assert LLMTier.SMALL == "small"
    assert LLMTier.MEDIUM == "medium"
    assert LLMTier.LARGE == "large"
    assert list(LLMTier) == [LLMTier.SMALL, LLMTier.MEDIUM, LLMTier.LARGE]


def test_error_hierarchy():
    assert issubclass(LLMTransientError, LLMError)
    assert issubclass(LLMPermanentError, LLMError)
    assert issubclass(LLMBudgetError, LLMPermanentError)


def test_stub_satisfies_protocol():
    stub = StubProvider(fallback="hi")
    assert isinstance(stub, LLMProvider)
    assert stub.provider_name == "stub"


async def test_stub_complete_fallback():
    stub = StubProvider(fallback="canned-fallback")
    out = await stub.complete(system="sys", user="anything")
    assert out == "canned-fallback"


async def test_stub_canned_exact_match():
    stub = StubProvider(canned_responses={("sys", "hello"): "HEY"}, fallback="default")
    assert await stub.complete("sys", "hello") == "HEY"
    assert await stub.complete("sys", "other") == "default"


async def test_stub_responder_callable():
    def responder(*, system, user, tier, **kw):
        return f"tier={tier} says {user}"

    stub = StubProvider(responder=responder)
    out = await stub.complete("sys", "ping", tier=LLMTier.LARGE)
    assert "tier=large" in out
    assert "says ping" in out


async def test_stub_async_responder():
    async def aresponder(**kw):
        return "async-ok"

    stub = StubProvider(responder=aresponder)
    out = await stub.complete("s", "u")
    assert out == "async-ok"


async def test_stub_stream_yields_once_from_complete():
    stub = StubProvider(fallback="streamed")
    pieces: list[str] = []
    async for chunk in stub.stream("s", "u"):
        pieces.append(chunk)
    assert pieces == ["streamed"]


async def test_stub_keyerror_when_no_canned_and_no_fallback():
    stub = StubProvider(canned_responses={("a", "b"): "x"}, fallback=None)
    assert await stub.complete("a", "b") == "x"
    with pytest.raises(KeyError):
        await stub.complete("zz", "nope")


def test_stub_model_for_returns_configured_or_default():
    stub = StubProvider(model_for_tier={LLMTier.LARGE: "big-model"})
    assert stub.model_for(LLMTier.LARGE) == "big-model"
    assert stub.model_for(LLMTier.SMALL) == "stub-model"
