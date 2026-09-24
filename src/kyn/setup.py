"""First-run setup helpers for the local desktop control room."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path


_BIN_DIRS = (
    Path.home() / ".local" / "bin",
    Path.home() / ".opencode" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)

_INSTALL_COMMANDS = {
    "kiro": ("Kiro CLI", "curl -fsSL https://cli.kiro.dev/install | bash"),
    "opencode": ("OpenCode", "curl -fsSL https://opencode.ai/install | bash"),
    # The ACP adapter is published by the Agent Client Protocol project and
    # brings along a compatible Codex CLI dependency.
    "codex": (
        "Codex",
        "npm install --global --prefix \"$HOME/.local\" @openai/codex @agentclientprotocol/codex-acp",
    ),
}


def _ensure_cli_path() -> None:
    """Add conventional user and Homebrew bin locations for GUI launches."""
    current = os.environ.get("PATH", "").split(os.pathsep)
    additions = [str(path) for path in _BIN_DIRS if path.is_dir()]
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys([*additions, *current]))


def _find_binary(name: str) -> str | None:
    _ensure_cli_path()
    found = shutil.which(name)
    if found:
        return found
    for directory in _BIN_DIRS:
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


async def setup_status() -> dict[str, object]:
    """Report which supported ACP engines are available on this machine."""
    engines: list[dict[str, object]] = []
    for engine, (label, _command) in _INSTALL_COMMANDS.items():
        binary_name = {"kiro": "kiro-cli", "opencode": "opencode", "codex": "codex-acp"}[engine]
        binary = _find_binary(binary_name)
        version = ""
        if binary:
            try:
                process = await asyncio.create_subprocess_exec(
                    binary,
                    "--version",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                output, _ = await asyncio.wait_for(process.communicate(), timeout=8)
                version = output.decode("utf-8", "replace").strip()[:160]
            except (OSError, TimeoutError):
                version = "Installed"
        engines.append(
            {
                "id": engine,
                "label": label,
                "available": binary is not None,
                "binary": binary or "",
                "version": version,
            }
        )
    return {"platform": sys.platform, "engines": engines}


async def install_engine(engine: str) -> dict[str, object]:
    """Run a fixed, official installer after an explicit user action."""
    selected = _INSTALL_COMMANDS.get(engine)
    if selected is None:
        raise ValueError("Choose Kiro CLI, OpenCode, or Codex.")
    if sys.platform != "darwin":
        raise RuntimeError("One-click CLI setup is currently available in the macOS app.")

    label, command = selected
    process = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-lc",
        command,
        cwd=str(Path.home()),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=600)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"{label} installation timed out. You can retry from setup.") from None

    _ensure_cli_path()
    log = output.decode("utf-8", "replace").strip()
    if process.returncode != 0:
        detail = log[-2400:] or f"Installer exited with status {process.returncode}."
        raise RuntimeError(detail)
    binary_name = {"kiro": "kiro-cli", "opencode": "opencode", "codex": "codex-acp"}[engine]
    binary = _find_binary(binary_name)
    if not binary:
        raise RuntimeError(
            f"{label} installer finished, but `{binary_name}` is not on the app's PATH. "
            "Restart Ari after completing the install."
        )
    return {"id": engine, "label": label, "binary": binary, "output": log[-2400:]}
