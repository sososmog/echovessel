"""Runtime subsystem — orchestrator + launcher + config + LLM providers.

Public surface:

    from echovessel.runtime import Runtime, load_config

The `echovessel` CLI binary (`runtime/launcher.py`) handles
run/stop/reload/status. User messages never go through the CLI — they
arrive via channels.
"""

from echovessel.runtime.app import (
    Runtime,
    RuntimeContext,
    build_sentence_transformers_embedder,
    build_zero_embedder,
)
from echovessel.runtime.config import (
    Config,
    LLMSection,
    load_config,
    load_config_from_str,
)

__all__ = [
    "Runtime",
    "RuntimeContext",
    "Config",
    "LLMSection",
    "load_config",
    "load_config_from_str",
    "build_sentence_transformers_embedder",
    "build_zero_embedder",
]
