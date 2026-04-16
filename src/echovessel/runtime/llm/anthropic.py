"""AnthropicProvider — native `anthropic` SDK backed LLMProvider.

See docs/runtime/01-spec-v0.1.md §6.2 / §6.2.1 / §6.2.2.

Tier → model resolution priority (§6.2.2):

    1. config.llm.model (pin-all-tiers override)
    2. config.llm.tier_models mapping
    3. Provider built-in defaults (only on official endpoint)
    4. ValueError at construction time
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Mapping

from echovessel.runtime.llm.base import LLMTier
from echovessel.runtime.llm.errors import (
    LLMBudgetError,
    LLMPermanentError,
    LLMTransientError,
)

log = logging.getLogger(__name__)

_TIER_DEFAULTS: dict[LLMTier, str] = {
    LLMTier.SMALL: "claude-haiku-4-5",
    LLMTier.MEDIUM: "claude-sonnet-4-6",
    LLMTier.LARGE: "claude-opus-4-6",
}

_OFFICIAL_BASE_URL = "https://api.anthropic.com"


class AnthropicProvider:
    """Wraps `anthropic.AsyncAnthropic` with the LLMProvider Protocol.

    Runtime holds a single instance; tier is a per-call parameter, not an
    instance property. The SDK is imported lazily so the `anthropic` package
    can live in the `[llm]` optional extra.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None = None,
        pinned_model: str | None = None,
        tier_models: Mapping[str, str] | None = None,
        default_max_tokens: int = 1024,
        default_temperature: float = 0.7,
        default_timeout: float = 60.0,
    ) -> None:
        self._pinned_model = pinned_model
        self._tier_models: dict[LLMTier, str] = {}
        if tier_models:
            for k, v in tier_models.items():
                try:
                    self._tier_models[LLMTier(k)] = v
                except ValueError:
                    raise ValueError(
                        f"Unknown tier in tier_models: {k!r} "
                        f"(expected one of {[t.value for t in LLMTier]})"
                    ) from None

        self._base_url_actual = base_url or _OFFICIAL_BASE_URL
        self._default_max_tokens = default_max_tokens
        self._default_temperature = default_temperature
        self._default_timeout = default_timeout

        # Validate at construction: every tier must resolve to a model.
        self._resolved_defaults: dict[LLMTier, str] = {}
        is_official = _is_official_anthropic(self._base_url_actual)
        for tier in LLMTier:
            if self._pinned_model:
                self._resolved_defaults[tier] = self._pinned_model
            elif tier in self._tier_models:
                self._resolved_defaults[tier] = self._tier_models[tier]
            elif is_official:
                self._resolved_defaults[tier] = _TIER_DEFAULTS[tier]
            else:
                raise ValueError(
                    f"AnthropicProvider: cannot resolve model for tier "
                    f"{tier.value!r}. Custom base_url={base_url!r} has no "
                    f"built-in defaults; set `llm.model` or "
                    f"`llm.tier_models.{tier.value}` in config."
                )

        # Client is built lazily because tests construct the provider
        # directly with fake api keys and don't want to require the SDK.
        self._api_key = api_key
        self._base_url_kwarg = base_url
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:
            raise ImportError(
                "anthropic SDK not installed. Install the [llm] extra: "
                "`uv sync --extra llm` or `pip install anthropic>=0.40`."
            ) from e
        client_kwargs: dict[str, object] = {}
        if self._api_key:
            client_kwargs["api_key"] = self._api_key
        if self._base_url_kwarg:
            client_kwargs["base_url"] = self._base_url_kwarg
        self._client = AsyncAnthropic(**client_kwargs)
        return self._client

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def base_url(self) -> str:
        return self._base_url_actual

    def model_for(self, tier: LLMTier) -> str:
        return self._resolved_defaults[tier]

    async def complete(
        self,
        system: str,
        user: str,
        *,
        tier: LLMTier = LLMTier.MEDIUM,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> str:
        model = self.model_for(tier)
        client = self._get_client()
        try:
            resp = await client.messages.create(  # type: ignore[attr-defined]
                model=model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens or self._default_max_tokens,
                temperature=temperature,
                timeout=timeout or self._default_timeout,
            )
        except Exception as e:  # noqa: BLE001
            raise _classify_anthropic_error(e) from e

        if not getattr(resp, "content", None):
            return ""
        parts: list[str] = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)

    async def stream(
        self,
        system: str,
        user: str,
        *,
        tier: LLMTier = LLMTier.MEDIUM,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        model = self.model_for(tier)
        client = self._get_client()
        try:
            async with client.messages.stream(  # type: ignore[attr-defined]
                model=model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens or self._default_max_tokens,
                temperature=temperature,
                timeout=timeout or self._default_timeout,
            ) as stream:
                async for delta in stream.text_stream:
                    yield delta
        except Exception as e:  # noqa: BLE001
            raise _classify_anthropic_error(e) from e


def _is_official_anthropic(url: str) -> bool:
    return "api.anthropic.com" in url


def _classify_anthropic_error(e: Exception) -> Exception:
    """Map anthropic SDK exceptions to our error hierarchy.

    Uses duck-typed `status_code` attribute; falls back to class name for
    timeout/connection-like errors so the mapping still works when the SDK
    is mocked.
    """
    status = getattr(e, "status_code", None)
    cls_name = e.__class__.__name__
    if status is None:
        if any(
            hint in cls_name for hint in ("Timeout", "Connection", "APIError", "Network")
        ):
            return LLMTransientError(f"{cls_name}: {e}")
        return LLMPermanentError(f"{cls_name}: {e}")

    if status == 429:
        return LLMTransientError(f"rate limited: {e}")
    if status >= 500:
        return LLMTransientError(f"server error {status}: {e}")
    if status in (401, 403):
        return LLMPermanentError(f"auth error {status}: {e}")
    if status == 402:
        return LLMBudgetError(f"budget/quota error {status}: {e}")
    return LLMPermanentError(f"client error {status}: {e}")


def build_anthropic_from_env(
    *,
    api_key_env: str,
    base_url: str | None = None,
    pinned_model: str | None = None,
    tier_models: Mapping[str, str] | None = None,
    **kwargs: object,
) -> AnthropicProvider:
    api_key = os.environ.get(api_key_env) if api_key_env else None
    return AnthropicProvider(
        api_key=api_key,
        base_url=base_url,
        pinned_model=pinned_model,
        tier_models=tier_models,
        **kwargs,  # type: ignore[arg-type]
    )


__all__ = ["AnthropicProvider", "build_anthropic_from_env"]
