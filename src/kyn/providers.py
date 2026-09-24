from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


class ProviderError(ValueError):
    """Raised when an agent engine is unknown, missing, or misconfigured."""


@dataclass(frozen=True, slots=True)
class EngineSpec:
    name: str
    label: str
    identity_namespace: str
    resume_native_conversation: bool
    supports_modes: bool
    supports_models: bool
    model_config_option: str | None = None


_ENGINES: dict[str, EngineSpec] = {
    "kiro": EngineSpec(
        name="kiro",
        label="Kiro",
        identity_namespace="kiro",
        resume_native_conversation=True,
        supports_modes=True,
        supports_models=True,
    ),
    "opencode": EngineSpec(
        name="opencode",
        label="OpenCode",
        identity_namespace="opencode",
        resume_native_conversation=False,
        supports_modes=False,
        supports_models=True,
        model_config_option="model",
    ),
    "codex": EngineSpec(
        name="codex",
        label="Codex",
        identity_namespace="codex",
        resume_native_conversation=False,
        supports_modes=False,
        supports_models=False,
    ),
}


def normalize_engine(value: str | None) -> str:
    name = (value or "kiro").strip().lower()
    if name not in _ENGINES:
        raise ProviderError(f"unknown agent engine {value!r}; expected one of: kiro, opencode, codex")
    return name


def spec(engine: str) -> EngineSpec:
    return _ENGINES[normalize_engine(engine)]


# Authoritative Kiro catalogue — mirrored by the UI (web-ui Dialogs.tsx).
_KIRO_MODEL_CATALOGUE: list[dict[str, str]] = [
    {"id": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5"},
    {"id": "claude-opus-4-1", "label": "Claude Opus 4.1"},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
    {"id": "claude-sonnet-4", "label": "Claude Sonnet 4"},
    {"id": "claude-opus-4", "label": "Claude Opus 4"},
    {"id": "claude-3-5-sonnet-latest", "label": "Claude 3.5 Sonnet"},
]

# Suggested Codex model ids (free-text ids are still accepted everywhere).
_CODEX_MODEL_SUGGESTIONS: list[dict[str, str]] = [
    {"id": "gpt-5.1-codex-max", "label": "GPT-5.1 Codex Max"},
    {"id": "gpt-5.1-codex", "label": "GPT-5.1 Codex"},
    {"id": "gpt-5.1-codex-mini", "label": "GPT-5.1 Codex Mini"},
    {"id": "o4-mini", "label": "o4-mini"},
]


def command_for(engine: str, cwd: str) -> list[str] | None:
    name = normalize_engine(engine)
    if name == "kiro":
        return None
    if name == "opencode":
        binary = shutil.which("opencode")
        if not binary:
            raise ProviderError("opencode is not installed or is not in PATH")
        return [binary, "acp", "--cwd", cwd]
    override = (os.environ.get("KYN_CODEX_ACP") or "").strip()
    binary = override or shutil.which("codex-acp") or ""
    if not binary:
        raise ProviderError(
            "codex-acp is not installed or is not in PATH; "
            "install the official Codex ACP bridge or set KYN_CODEX_ACP to its path"
        )
    return [binary]


def models_for(engine: str) -> list[dict[str, str]]:
    """List selectable native models for an engine.

    OpenCode reads its live model registry from the local CLI. Kiro uses the
    curated catalogue the rest of the product ships; Codex models are a
    suggestion set (Codex accepts free-text model ids everywhere).
    """
    name = normalize_engine(engine)
    if name == "kiro":
        return [dict(item) for item in _KIRO_MODEL_CATALOGUE]
    if name == "codex":
        return [dict(item) for item in _CODEX_MODEL_SUGGESTIONS]
    if name != "opencode":
        raise ProviderError(f"model listing is not supported for engine {name!r}")
    binary = shutil.which("opencode")
    if not binary:
        raise ProviderError("opencode is not installed or is not in PATH")
    try:
        completed = subprocess.run(
            [binary, "models"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProviderError(f"could not list OpenCode models: {exc}") from exc
    if completed.returncode != 0:
        raise ProviderError("could not list OpenCode models")
    models = []
    for line in completed.stdout.decode("utf-8", "replace").splitlines():
        model_id = line.strip()
        if model_id and "/" in model_id:
            models.append({"id": model_id, "label": model_id})
    return models


def initialize_params(engine: str) -> dict:
    name = normalize_engine(engine)
    capabilities = {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}
    if name == "kiro":
        return {
            "clientInfo": {"name": "kyn", "version": "0.1.0"},
            "protocolVersion": "2025-08-22",
            "clientCapabilities": capabilities,
        }
    return {
        "protocolVersion": 1,
        "clientCapabilities": capabilities,
        "clientInfo": {"name": "kyn", "version": "0.1.0"},
    }
