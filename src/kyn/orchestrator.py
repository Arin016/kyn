from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncIterator

from .protocol import Event
from .plugins import PluginRegistry
from .providers import ProviderError, command_for, initialize_params, spec
from .runtime import AcpError, AcpRuntime
from .session import AcpSession
from .store import Bot, Store

_LOGGER = logging.getLogger(__name__)


class BotOrchestrator:
    def __init__(
        self,
        store: Store | None = None,
        plugins: PluginRegistry | None = None,
    ) -> None:
        self.store = store or Store()
        self.plugins = plugins or PluginRegistry(self.store)
        self.runtime: AcpRuntime | None = None
        self.session: AcpSession | None = None
        self.bot: Bot | None = None
        self._plugin_generation: int | None = None
        self._cwd_override: Path | None = None

    async def open(
        self,
        bot_name: str,
        *,
        cwd: str | Path | None = None,
    ) -> AcpSession:
        if self.runtime is not None:
            await self.close()
        cwd_override = _validated_cwd(cwd) if cwd is not None else None
        # A registry mutation can race session initialization. Retry a bounded
        # number of times and publish only a session whose generation is still
        # current; otherwise fail closed rather than expose stale capabilities.
        for _attempt in range(3):
            bot = self.store.get_bot(bot_name)
            if bot is None:
                raise AcpError(f"unknown bot {bot_name!r}; create it first")
            try:
                engine = spec(bot.engine)
            except ProviderError as exc:
                raise AcpError(str(exc)) from exc
            if bot.mcp_servers:
                raise AcpError(
                    "legacy inline MCP configuration is disabled; migrate this bot's "
                    "servers into the governed plugin registry"
                )
            generation, registry_servers = self.plugins.compile_session_configuration(
                bot.name
            )
            mcp_servers = registry_servers
            names = [str(server.get("name") or "") for server in mcp_servers]
            if not all(names) or len(names) != len(set(names)):
                raise AcpError("MCP server names must be non-empty and unique for this bot")
            self.bot = bot
            self._plugin_generation = generation
            self._cwd_override = cwd_override
            runtime_cwd = cwd_override or Path(bot.cwd).expanduser().resolve()
            try:
                command = command_for(engine.name, str(runtime_cwd))
            except ProviderError as exc:
                raise AcpError(str(exc)) from exc
            self.runtime = AcpRuntime(
                runtime_cwd,
                agent=bot.agent if engine.supports_modes else "",
                model=bot.model if engine.supports_models else "",
                effort=bot.effort if engine.name == "kiro" else "",
                command=command,
                engine_label=engine.label,
                initialize_params=initialize_params(engine.name),
                identity_namespace=engine.identity_namespace,
            )
            await self.runtime.start()

            # A per-run workspace is an isolated execution context. Reusing or
            # replacing the bot's durable conversation would mix cwd-specific
            # context and make a later normal chat point at the wrong tree.
            # Explicit model resets clear the saved conversation in
            # Engine.set_bot_model. An empty model at ordinary startup means
            # "use the engine default" and must still resume the durable thread.
            saved = None
            if cwd_override is None and engine.resume_native_conversation:
                saved = self.store.conversation(bot.name)
            if saved:
                session_id, transcript_path = saved
                try:
                    self.session = await self.runtime.load_session(
                        session_id,
                        transcript_path=transcript_path,
                        mcp_servers=mcp_servers,
                    )
                except AcpError as exc:
                    _LOGGER.warning(
                        "Could not resume saved native session for bot %s; "
                        "starting a fresh session with durable memory fallback: %s",
                        bot.name,
                        exc,
                    )
                    self.session = None
                    # Kiro 2.19 may exit just after returning a load error. There is
                    # a race where returncode is still None but the next write is
                    # already doomed, so always replace the transport before the
                    # fresh-session fallback.
                    await self.runtime.close()
                    self.runtime = AcpRuntime(
                        runtime_cwd,
                        agent=bot.agent if engine.supports_modes else "",
                        model=bot.model if engine.supports_models else "",
                        effort=bot.effort if engine.name == "kiro" else "",
                        command=command,
                        engine_label=engine.label,
                        initialize_params=initialize_params(engine.name),
                        identity_namespace=engine.identity_namespace,
                    )
                    await self.runtime.start()

            if saved and self.session is not None and engine.supports_models and bot.model:
                # Resume must honor the bot's configured model too — a saved
                # session restores whatever model it last ran with.
                try:
                    if engine.model_config_option:
                        await self.session.set_config_option(engine.model_config_option, bot.model)
                    else:
                        await self.session.set_model(bot.model)
                except AcpError:
                    _LOGGER.warning(
                        "Could not apply model %r to resumed session for %s",
                        bot.model,
                        bot.name,
                    )

            if self.session is None:
                self.session = await self.runtime.create_session(mcp_servers)
                if engine.supports_modes and bot.agent:
                    await self.session.set_mode(bot.agent)
                if engine.supports_models and bot.model:
                    if engine.model_config_option:
                        await self.session.set_config_option(engine.model_config_option, bot.model)
                    else:
                        await self.session.set_model(bot.model)

            if self.plugins.config_generation(bot.name) != generation:
                await self.close()
                continue
            transcript = (
                str(_kiro_transcript(self.session.session_id))
                if engine.name == "kiro"
                else ""
            )
            if cwd_override is None and engine.resume_native_conversation:
                self.store.save_conversation(bot.name, self.session.session_id, transcript)
            return self.session
        raise AcpError("plugin configuration changed repeatedly during session startup")

    async def run(self, message: str) -> AsyncIterator[Event]:
        if self.bot is None or self.session is None:
            raise AcpError("open a bot before running a turn")
        bot_name = self.bot.name
        if self._plugin_generation != self.plugins.config_generation(bot_name):
            # BotWorker serializes turns for one bot, so this refresh cannot
            # interrupt another prompt on the same orchestrator.
            await self.open(bot_name, cwd=self._cwd_override)
            if self.bot is None or self.session is None:
                raise AcpError("could not refresh bot after plugin configuration changed")
        turn_id = self.store.begin_turn(self.bot.name, message, engine=self.bot.engine)
        sequence = 0
        stop_reason = ""
        try:
            async for event in self.session.prompt(message):
                sequence += 1
                self.store.add_event(turn_id, sequence, event)
                if event.kind == "complete":
                    stop_reason = event.stop_reason
                yield event
            self.store.finish_turn(turn_id, "complete", stop_reason)
        except BaseException:
            self.store.finish_turn(turn_id, "failed", stop_reason)
            raise

    async def close(self) -> None:
        if self.runtime:
            await self.runtime.close()
        self.runtime = None
        self.session = None
        self.bot = None
        self._plugin_generation = None
        self._cwd_override = None

    async def __aenter__(self) -> "BotOrchestrator":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


def _kiro_transcript(session_id: str) -> Path:
    return Path("~/.kiro/sessions/cli").expanduser() / f"{session_id}.json"


def _validated_cwd(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise AcpError("execution cwd cannot be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AcpError("execution cwd must be an existing directory") from exc
    if not resolved.is_dir():
        raise AcpError("execution cwd must be an existing directory")
    return resolved
