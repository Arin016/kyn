"""HTTP and WebSocket control plane for Ari.

FastAPI is intentionally an optional dependency of the core package.  Importing
this module remains safe without it; :func:`create_app` explains how to enable
the server when called.
"""

from __future__ import annotations

import inspect
import hmac
import json
import logging
import re
import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

from .governance import GovernanceStore, Policy, QuotaExceeded
from .delegation import (
    DelegationCoordinator,
    DelegationStore,
    EdgeSpec,
    NodeSpec,
    PlanNotFound,
)
from .plugins import PluginRegistry, PluginRegistryError
from .plugins import PluginConflictError, PluginNotFoundError
from .run_store import RunRepository
from .routines import RoutineNotFound, RoutineStore, Scheduler
from .memory import SharedMemoryStore
from .chief import ensure_chief_of_staff
from .internal_control import CONTROL_PLUGIN_ID, ensure_bot_control, ensure_internal_control
from .groups import GroupCoordinator, GroupNotFound, GroupStore
from .interactions import InteractionConflict, InteractionNotFound, InteractionStore
from . import providers
from .handoff import HandoffError, compile_handoff
from .store import Bot, Store
from .workspaces import WorkspaceError, WorkspaceLease, WorkspaceManager
from .coding_lifecycle import (
    CheckSpec,
    CodingExecutionConflict,
    CodingExecutionNotFound,
    CodingExecutionSpec,
    CodingExecutionStore,
    CodingLifecycleController,
    CodingLifecycleError,
)
from .live import LiveBus
from .concierge import ensure_concierge
from .plugin_place import PlaceError, catalog_view, install_template
from .tasks import TaskStore
from .tasks import TaskConflict, TaskError
from .tasks import commit_worktree, create_task_branch
from .tasks import delete_task_branch, derive_task_state
from .tasks import merge_marker, merge_task_branch, push_to_branch
from .tasks import remove_worktree, resolve_base, resolve_commit
from .tasks import worktree_diff, worktree_is_clean
from .delegation_guard import GATED_TOOLS as DELEGATION_GATED_TOOLS
from .delegation_guard import authorize as authorize_delegation_tool
from .remote import authorize_websocket, install_remote_guard
from .setup import install_engine, setup_status
from .channels import (
    ChannelAuthenticationError,
    ChannelAuthorizationError,
    ChannelError,
    ChannelGateway,
    ChannelNotFound,
    ChannelStore,
    email_event,
    generic_event,
    github_event,
    resolve_secret,
    resolve_verify_token,
    slack_event,
    verify_kiro_webhook,
    verify_sha256,
    verify_slack,
    whatsapp_events,
)

try:  # Keep the ACP/CLI-only installation dependency-free.
    from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
    from starlette.websockets import WebSocketDisconnect
except ImportError as _fastapi_import_error:  # pragma: no cover - environment-specific
    FastAPI = None  # type: ignore[assignment,misc]
    _FASTAPI_IMPORT_ERROR: ImportError | None = _fastapi_import_error
else:
    _FASTAPI_IMPORT_ERROR = None


_BOT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PERMISSION_DECISIONS = frozenset({"once", "reject"})
_logger = logging.getLogger(__name__)


if FastAPI is not None:

    class CreateBotBody(BaseModel):
        name: str = Field(min_length=1, max_length=64)
        cwd: str = Field(min_length=1)
        agent: str | None = None
        model: str | None = None
        effort: str | None = None
        engine: str | None = None
        brief: str | None = Field(default=None, max_length=8000)


    class TurnBody(BaseModel):
        message: str = Field(min_length=1)

    class RetryBody(BaseModel):
        # Edited replacement for the turn's prompt. Omitted = retry verbatim.
        message: str | None = None

    class ForkBody(BaseModel):
        to_bot: str = Field(min_length=1, max_length=128)
        budget_tokens: int = Field(default=12000, ge=500, le=50000)

    class AuthorizeBody(BaseModel):
        caller: str = Field(min_length=1, max_length=128)
        tool: str = Field(min_length=1, max_length=128)

    class UpdateBotBody(BaseModel):
        model: str | None = None
        effort: str | None = None
        agent: str | None = None
        cwd: str | None = None
        brief: str | None = Field(default=None, max_length=8000)


    class BotModelBody(BaseModel):
        model: str = Field(default="", max_length=200)


    class HandoffBody(BaseModel):
        to_engine: str = Field(min_length=1, max_length=32)
        budget_tokens: int = Field(default=12_000, ge=500, le=200_000)


    class PermissionBody(BaseModel):
        decision: str = Field(min_length=1)


    class PolicyBody(BaseModel):
        # All fields are optional: a PUT merges onto the stored policy, so a
        # client that only manages approvals cannot wipe failover (or quota)
        # settings it never sent.
        approval_mode: str | None = None
        allowed_tools: list[str] | None = None
        denied_tools: list[str] | None = None
        max_turns_per_hour: int | None = Field(default=None, ge=0)
        max_concurrent_runs: int | None = Field(default=None, ge=0)
        max_daily_runs: int | None = Field(default=None, ge=0)
        auto_failover: bool | None = None
        failover_engines: list[str] | None = None


    class CreateRoutineBody(BaseModel):
        name: str = Field(min_length=1, max_length=100)
        bot_name: str = Field(min_length=1, max_length=100)
        prompt: str = Field(min_length=1)
        trigger_kind: str
        interval_seconds: int | None = None
        run_at: str | None = None
        enabled: bool = True


    class UpdateRoutineBody(BaseModel):
        name: str | None = None
        bot_name: str | None = None
        prompt: str | None = None
        trigger_kind: str | None = None
        interval_seconds: int | None = None
        run_at: str | None = None
        enabled: bool | None = None


    class CreatePluginBody(BaseModel):
        id: str = Field(min_length=1, max_length=64)
        name: str = Field(min_length=1, max_length=100)
        transport: str
        command: str = ""
        args: list[str] = Field(default_factory=list)
        url: str = ""
        env: dict[str, str] = Field(default_factory=dict)
        enabled: bool = True


    class BindPluginBody(BaseModel):
        enabled: bool = True
        allow_tools: list[str] = Field(default_factory=lambda: ["*"])
        deny_tools: list[str] = Field(default_factory=list)
        auto_approve_tools: list[str] = Field(default_factory=list)
        timeout_ms: int = Field(default=60_000, ge=1, le=3_600_000)


    class DelegationNodeBody(BaseModel):
        id: str = Field(min_length=1, max_length=100)
        bot_name: str = Field(min_length=1, max_length=100)
        prompt: str = Field(min_length=1)


    class DelegationEdgeBody(BaseModel):
        source: str = Field(min_length=1, max_length=100)
        target: str = Field(min_length=1, max_length=100)


    class CreateDelegationBody(BaseModel):
        name: str = Field(min_length=1, max_length=100)
        nodes: list[DelegationNodeBody] = Field(min_length=1)
        edges: list[DelegationEdgeBody] = Field(default_factory=list)
        max_fanout: int = Field(default=4, ge=1, le=32)
        max_depth: int = Field(default=4, ge=0, le=32)
        start: bool = True


    class CreateWorkspaceBody(BaseModel):
        repo_path: str = Field(min_length=1)
        ref: str = Field(default="HEAD", min_length=1, max_length=200)
        run_id: str = Field(min_length=1, max_length=120)
        bot_name: str = Field(default="", max_length=100)
        lease_seconds: int = Field(default=3600, ge=1, le=86_400)


    class FinalizeWorkspaceBody(BaseModel):
        token: str = Field(min_length=1)
        outcome: str = "completed"
        artifact_paths: list[str] | None = None


    class WorkspaceLeaseBody(BaseModel):
        token: str = Field(min_length=1)


    class CodingCheckBody(BaseModel):
        name: str = Field(min_length=1, max_length=100)
        argv: list[str] = Field(min_length=1, max_length=64)
        timeout_seconds: float = Field(default=600, gt=0, le=3600)


    class CreateCodingExecutionBody(BaseModel):
        idempotency_key: str = Field(min_length=1, max_length=160)
        repo_path: str = Field(min_length=1)
        ref: str = Field(default="HEAD", min_length=1, max_length=256)
        task: str = Field(min_length=1, max_length=100_000)
        builder_bot: str = Field(min_length=1, max_length=100)
        reviewer_bot: str = Field(min_length=1, max_length=100)
        checks: list[CodingCheckBody] = Field(min_length=1, max_length=20)
        max_repairs: int = Field(default=1, ge=0, le=3)
        timeout_seconds: float = Field(default=1800, ge=30, le=86_400)


    class CodingHandoffBody(BaseModel):
        expected_version: int = Field(ge=1)


    class MemoryFactBody(BaseModel):
        fact: str = Field(min_length=1, max_length=2000)
        entities: list[str] = Field(default_factory=list, max_length=20)
        source: str = Field(default="", max_length=500)
        actor: str = Field(default="api", max_length=100)


    class MemorySupersedeBody(BaseModel):
        fact: str = Field(min_length=1, max_length=2000)
        entities: list[str] = Field(default_factory=list, max_length=20)
        source: str = Field(default="", max_length=500)
        actor: str = Field(default="api", max_length=100)


    class MemoryPinBody(BaseModel):
        pinned: bool = True


    class DreamBody(BaseModel):
        interval_seconds: int = Field(default=86400, ge=3600, le=604800)


    class InstallPlaceBody(BaseModel):
        template_id: str = Field(min_length=1, max_length=64)
        bot_names: list[str] = Field(min_length=1, max_length=12)
        config: dict[str, str] = Field(default_factory=dict)


    class PluginSecretBody(BaseModel):
        name: str = Field(min_length=1, max_length=128)
        value: str = Field(min_length=1, max_length=8192)


    class CreateTaskBody(BaseModel):
        builder_bot: str = Field(min_length=1, max_length=100)
        reviewer_bot: str = Field(min_length=1, max_length=100)
        repo_path: str = Field(min_length=1)
        task: str = Field(min_length=1, max_length=100_000)
        base: str = Field(default="HEAD", min_length=1, max_length=256)
        checks: list[CodingCheckBody] = Field(min_length=1, max_length=20)
        max_repairs: int = Field(default=1, ge=0, le=3)
        timeout_seconds: float = Field(default=1800, ge=30, le=86_400)


    class MergeTaskBody(BaseModel):
        message: str | None = Field(default=None, max_length=500)


    class CreateChannelBody(BaseModel):
        id: str = Field(min_length=1, max_length=80)
        name: str = Field(min_length=1, max_length=100)
        kind: str
        bot_name: str = Field(min_length=1, max_length=100)
        signing_secret_env: str = Field(min_length=1, max_length=200)
        verify_token_env: str = Field(default="", max_length=200)
        outbound_token_env: str = Field(default="", max_length=200)
        trigger_prefix: str = Field(default="@kiro", max_length=100)
        allowed_sources: list[str] = Field(default_factory=list, max_length=100)
        allowed_senders: list[str] = Field(default_factory=list, max_length=100)
        enabled: bool = True


    class UpdateChannelBody(BaseModel):
        enabled: bool


    class CreateGroupBody(BaseModel):
        name: str = Field(min_length=1, max_length=100)
        aim: str = Field(min_length=1, max_length=4_000)
        members: list[str] = Field(min_length=1, max_length=12)
        max_rounds: int = Field(default=2, ge=1, le=10)
        reply_mode: str = Field(default="sequential", min_length=1, max_length=16)
        start: bool = True


    class GroupMessageBody(BaseModel):
        text: str = Field(min_length=1, max_length=8_000)
        respond: bool = True
        mentions: list[str] = Field(default_factory=list, max_length=12)

    class GroupContextBody(BaseModel):
        note: str = Field(default="", max_length=4_000)


    class GroupModeBody(BaseModel):
        mode: str = Field(min_length=1, max_length=16)


def create_app(
    store: Store | None = None,
    engine: Any | None = None,
    *,
    governance: GovernanceStore | None = None,
    routines: RoutineStore | None = None,
    plugins: PluginRegistry | None = None,
    scheduler: Scheduler | None = None,
    delegations: DelegationStore | None = None,
    delegation_coordinator: DelegationCoordinator | None = None,
    workspaces: WorkspaceManager | None = None,
    coding_controller: CodingLifecycleController | None = None,
    channels: ChannelStore | None = None,
    channel_gateway: ChannelGateway | None = None,
    groups: GroupStore | None = None,
    group_coordinator: GroupCoordinator | None = None,
    live: LiveBus | None = None,
) -> Any:
    """Create the local daemon application.

    ``store`` and ``engine`` are injectable so the transport can be tested and
    embedded without starting Kiro.  The engine contract is deliberately small:
    ``start``, ``close``, ``submit``, ``get_run``, ``subscribe``,
    ``decide_permission`` and ``cancel``.
    """

    if FastAPI is None:
        raise RuntimeError(
            "The daemon requires the optional server dependencies. "
            "Install kyn with its server extra (for example: "
            "pip install 'kyn[server]')."
        ) from _FASTAPI_IMPORT_ERROR

    active_store = store or Store()
    active_governance = governance or GovernanceStore(active_store)
    active_plugins = plugins or PluginRegistry(active_store)
    ensure_internal_control(active_store, active_plugins)
    ensure_chief_of_staff(active_store, active_plugins)
    ensure_concierge(active_store, active_plugins)
    active_routines = routines or RoutineStore(active_store)
    active_delegations = delegations or DelegationStore(active_store)
    active_runs = RunRepository(active_store)
    active_memory = SharedMemoryStore(active_store)
    active_interactions = InteractionStore(active_store)
    active_memory.backfill_local_history()
    active_workspaces = workspaces or WorkspaceManager(
        active_store, active_store.home / "workspaces"
    )
    active_engine = engine or _make_engine(
        active_store,
        active_governance,
        active_plugins,
        active_workspaces,
        active_memory,
        active_interactions,
    )
    active_coding_store = CodingExecutionStore(active_store)
    active_tasks = TaskStore(active_store)
    active_memory.backfill_coding_history()
    active_coding_controller = coding_controller or CodingLifecycleController(
        active_coding_store, active_engine, active_workspaces, memory=active_memory
    )
    active_channels = channels or ChannelStore(active_store)
    active_groups = groups or GroupStore(active_store)
    active_live = live or LiveBus()

    async def engine_submit(
        bot_name: str,
        message: str,
        actor: str,
        run_id: str | None = None,
    ) -> object:
        submit = active_engine.submit
        try:
            parameters = inspect.signature(submit).parameters
        except (TypeError, ValueError):
            parameters = {}
        kwargs: dict[str, Any] = {}
        if "actor" in parameters:
            kwargs["actor"] = actor
        if run_id is not None and "run_id" in parameters:
            kwargs["run_id"] = run_id
        return await _maybe_await(submit(bot_name, message, **kwargs))

    async def scheduled_submit(bot_name: str, message: str) -> object:
        return await engine_submit(bot_name, message, "scheduler")

    async def delegated_submit(
        bot_name: str,
        message: str,
        run_id: str | None = None,
    ) -> str:
        return _run_id(
            await engine_submit(bot_name, message, "delegation", run_id=run_id)
        )

    async def delegated_wait(run_id: str) -> Mapping[str, Any]:
        while True:
            snapshot = await _get_run(active_engine, run_id)
            mapped = _mapping(snapshot)
            if mapped is not None and str(mapped.get("status", "")) in {
                "complete",
                "failed",
                "cancelled",
            }:
                return mapped
            if snapshot is not None:
                try:
                    subscription = active_engine.subscribe(run_id, 0)
                    if inspect.isawaitable(subscription):
                        subscription = await subscription
                    async for _event in subscription:
                        pass
                except KeyError:
                    # The in-memory retention window may have evicted a run;
                    # its terminal state remains available in RunRepository.
                    pass
                else:
                    completed = _mapping(await _get_run(active_engine, run_id))
                    if completed is not None:
                        return completed
            durable = await asyncio.to_thread(active_runs.get, run_id)
            if durable is None:
                return {"status": "failed", "error": "delegated run was not found"}
            if durable.status in {"complete", "failed", "cancelled"}:
                return {
                    "id": durable.run_id,
                    "status": durable.status,
                    "started_at": durable.started_at,
                    "finished_at": durable.finished_at,
                    "attempt": durable.attempt,
                }
            # Engine startup restores queued durable runs before delegation
            # plans launch. This brief fallback also covers retention races.
            await asyncio.sleep(0.05)

    async def run_interactions(run_id: str) -> list[Mapping[str, Any]]:
        items = await asyncio.to_thread(
            active_interactions.list, status="pending", run_id=run_id, limit=500
        )
        return [item.summary() for item in items]

    async def channel_interaction_decision(
        interaction_id: str,
        decision: str,
        actor: str,
        binding: Any,
    ) -> dict[str, Any]:
        interaction = await asyncio.to_thread(
            active_interactions.require, interaction_id
        )
        expected_actor = f"channel:{binding.kind}:{binding.id}"
        if interaction.actor != expected_actor or interaction.bot_name != binding.bot_name:
            raise ChannelAuthorizationError("interaction does not belong to this channel")
        await _maybe_await(
            active_engine.decide_permission(
                interaction.run_id, interaction.request_id, decision
            )
        )
        resolved = await asyncio.to_thread(
            active_interactions.resolve,
            interaction_id,
            decision,
            actor=actor,
        )
        return resolved.summary()

    active_channel_gateway = channel_gateway or ChannelGateway(
        active_channels,
        engine_submit,
        delegated_wait,
        memory=active_memory,
        live=active_live,
        list_interactions=run_interactions,
        decide_interaction=channel_interaction_decision,
    )

    async def group_submit(bot_name: str, message: str) -> str:
        return _run_id(await engine_submit(bot_name, message, "group"))

    active_scheduler = scheduler or Scheduler(active_routines, scheduled_submit)
    active_group_coordinator = group_coordinator or GroupCoordinator(
        active_groups,
        group_submit,
        delegated_wait,
        cancel=lambda run_id: active_engine.cancel(run_id),
    )
    active_delegation_coordinator = delegation_coordinator or DelegationCoordinator(
        active_delegations,
        delegated_submit,
        delegated_wait,
        cancel=lambda run_id: active_engine.cancel(run_id),
    )
    delegation_tasks: dict[str, asyncio.Task[Any]] = {}

    def delegation_done(task: asyncio.Task[Any], plan_id: str) -> None:
        delegation_tasks.pop(plan_id, None)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            _logger.error(
                "Delegation plan %s stopped unexpectedly",
                plan_id,
                exc_info=(type(exception), exception, exception.__traceback__),
            )

    def launch_delegation(plan_id: str) -> None:
        existing = delegation_tasks.get(plan_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(
            active_delegation_coordinator.run_until_terminal(plan_id),
            name=f"kyn-delegation:{plan_id}",
        )
        delegation_tasks[plan_id] = task
        task.add_done_callback(lambda finished, key=plan_id: delegation_done(finished, key))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.store = active_store
        app.state.engine = active_engine
        app.state.governance = active_governance
        app.state.routines = active_routines
        app.state.plugins = active_plugins
        app.state.scheduler = active_scheduler
        app.state.delegations = active_delegations
        app.state.delegation_coordinator = active_delegation_coordinator
        app.state.workspaces = active_workspaces
        app.state.memory = active_memory
        app.state.interactions = active_interactions
        app.state.coding_controller = active_coding_controller
        app.state.channels = active_channels
        app.state.channel_gateway = active_channel_gateway
        app.state.groups = active_groups
        app.state.group_coordinator = active_group_coordinator
        app.state.live = active_live
        engine_start_attempted = False
        coding_start_attempted = False
        channel_start_attempted = False
        scheduler_start_attempted = False
        try:
            engine_start_attempted = True
            await _maybe_await(active_engine.start())
            coding_start_attempted = True
            await _maybe_await(active_coding_controller.start())
            channel_start_attempted = True
            await _maybe_await(active_channel_gateway.start())
            scheduler_start_attempted = True
            await _maybe_await(active_scheduler.start())
            for plan in active_delegations.list_plans():
                if plan.status in {"pending", "running"}:
                    launch_delegation(plan.id)
            yield
        finally:
            tasks = list(delegation_tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await _maybe_await(active_group_coordinator.close())
                await _maybe_await(active_delegation_coordinator.close())
            finally:
                try:
                    if scheduler_start_attempted:
                        await _maybe_await(active_scheduler.close())
                finally:
                    try:
                        if channel_start_attempted:
                            await _maybe_await(active_channel_gateway.close())
                    finally:
                        try:
                            if coding_start_attempted:
                                await _maybe_await(active_coding_controller.close())
                        finally:
                            if engine_start_attempted:
                                await _maybe_await(active_engine.close())

    app = FastAPI(title="Ari", version="0.1.0", lifespan=lifespan)
    install_remote_guard(app)
    # State is also populated immediately for ASGI hosts that inspect the app
    # before entering its lifespan.
    app.state.store = active_store
    app.state.engine = active_engine
    app.state.governance = active_governance
    app.state.routines = active_routines
    app.state.plugins = active_plugins
    app.state.scheduler = active_scheduler
    app.state.delegations = active_delegations
    app.state.delegation_coordinator = active_delegation_coordinator
    app.state.workspaces = active_workspaces
    app.state.memory = active_memory
    app.state.interactions = active_interactions
    app.state.coding_controller = active_coding_controller
    app.state.channels = active_channels
    app.state.channel_gateway = active_channel_gateway
    app.state.groups = active_groups
    app.state.group_coordinator = active_group_coordinator
    app.state.live = active_live

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "invalid_request", "detail": _json_safe(exc.errors())})

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        # Prompts, local paths and provider details can occur in exceptions.
        # Preserve those only in server logs, never in the wire response.
        _logger.exception("Unhandled Ari API error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": "The request could not be completed"},
        )

    @app.exception_handler(QuotaExceeded)
    async def quota_exceeded(_request: Request, exc: QuotaExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"error": "quota_exceeded", "quota": exc.quota},
        )

    @app.exception_handler(PluginNotFoundError)
    async def plugin_not_found(
        _request: Request, _exc: PluginNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": "plugin_not_found"})

    @app.exception_handler(PluginConflictError)
    async def plugin_conflict(
        _request: Request, exc: PluginConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": "plugin_conflict", "detail": str(exc)},
        )

    @app.exception_handler(PluginRegistryError)
    async def plugin_error(_request: Request, exc: PluginRegistryError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_plugin_configuration", "detail": str(exc)},
        )

    @app.exception_handler(InteractionNotFound)
    async def interaction_not_found(
        _request: Request, _exc: InteractionNotFound
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": "interaction_not_found"})

    @app.exception_handler(InteractionConflict)
    async def interaction_conflict(
        _request: Request, exc: InteractionConflict
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": "interaction_conflict", "detail": str(exc)},
        )

    @app.exception_handler(CodingExecutionConflict)
    async def coding_conflict(
        _request: Request, exc: CodingExecutionConflict
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": "coding_execution_conflict", "detail": str(exc)},
        )

    @app.exception_handler(CodingLifecycleError)
    async def coding_lifecycle_error(
        _request: Request, exc: CodingLifecycleError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_coding_execution", "detail": str(exc)},
        )

    @app.exception_handler(ChannelNotFound)
    async def channel_not_found(_request: Request, _exc: ChannelNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": "channel_not_found"})

    @app.exception_handler(GroupNotFound)
    async def group_not_found(_request: Request, _exc: GroupNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": "group_not_found"})

    @app.exception_handler(ChannelAuthenticationError)
    async def channel_authentication_error(
        _request: Request, _exc: ChannelAuthenticationError
    ) -> JSONResponse:
        return JSONResponse(status_code=401, content={"error": "invalid_channel_signature"})

    @app.exception_handler(ChannelAuthorizationError)
    async def channel_authorization_error(
        _request: Request, _exc: ChannelAuthorizationError
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"error": "channel_event_not_allowed"})

    @app.exception_handler(ChannelError)
    async def channel_error(_request: Request, exc: ChannelError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "channel_error", "detail": str(exc)})

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.get("/api/setup/status")
    async def get_setup_status() -> dict[str, Any]:
        return await setup_status()

    @app.post("/api/setup/install/{engine}")
    async def setup_install_engine(engine: str, request: Request) -> dict[str, Any]:
        origin = (request.headers.get("origin") or "").rstrip("/")
        expected_origin = str(request.base_url).rstrip("/")
        if not origin or origin != expected_origin:
            raise HTTPException(status_code=403, detail="setup installs must come from this Ari app")
        try:
            return await install_engine(engine)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/bots")
    async def list_bots() -> list[dict[str, Any]]:
        return [_bot_payload(bot) for bot in active_store.list_bots()]

    def _publish_roster(scope: str, action: str, name: str) -> None:
        """Push a roster change to live control rooms (sidebar, groups).

        Polling is not how production stays fresh — every in-daemon bot/group
        mutation announces itself on the live bus so connected windows update
        in the same beat the change commits.
        """
        try:
            active_live.publish(
                {"type": "roster", "scope": scope, "action": action, "name": name}
            )
        except Exception:
            pass

    @app.post("/api/bots", status_code=201)
    async def create_bot(body: CreateBotBody) -> dict[str, Any]:
        name = _validate_bot_name(body.name)
        cwd = _validate_working_directory(body.cwd)
        try:
            bot = Bot(
                name=name,
                cwd=str(cwd),
                agent=(body.agent or "").strip(),
                model=(body.model or "").strip(),
                effort=(body.effort or "").strip(),
                engine=(body.engine or "kiro").strip(),
                brief=(body.brief or "").strip(),
            )
            active_store.put_bot(bot)
        except (TypeError, ValueError) as exc:
            # Unknown engine ids surface here (normalize_engine); a typo is a
            # 422, not a 500.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        ensure_bot_control(active_plugins, bot.name)
        _publish_roster("bots", "created", bot.name)
        return _bot_payload(bot)

    @app.delete("/api/bots/{name}", status_code=200)
    async def delete_bot(name: str) -> dict[str, Any]:
        """Delete a bot permanently; routines and bindings go with it."""
        bot = _require_bot(active_store, name)
        for routine in active_routines.list(bot_name=bot.name):
            active_routines.delete(str(getattr(routine, "id", "")))
        for binding in active_plugins.binding_summaries(bot.name):
            active_plugins.unbind_plugin(bot.name, str(binding.get("plugin_id") or ""))
        try:
            active_governance.set_policy(
                bot.name,
                Policy(
                    approval_mode="deny_all",
                    allowed_tools=(),
                    denied_tools=("*",),
                    max_turns_per_hour=1,
                    max_concurrent_runs=1,
                    max_daily_runs=1,
                ),
            )
        except (TypeError, ValueError):
            pass
        with active_store.connect() as db:
            cursor = db.execute("DELETE FROM bots WHERE name = ?", (bot.name,))
            deleted = bool(cursor.rowcount)
            if deleted:
                # Pending interactions name a bot that no longer exists: they
                # can never be decided, and unfiltered listings would surface
                # orphan rows. Audit history is deliberately retained.
                db.execute("DELETE FROM interactions WHERE bot_name = ?", (bot.name,))
        if not deleted:
            raise HTTPException(status_code=404, detail=f"bot {name!r} was not found")
        _publish_roster("bots", "deleted", bot.name)
        return {"deleted": True, "name": bot.name}

    @app.get("/api/bots/{name}")
    async def get_bot(name: str) -> dict[str, Any]:
        bot = _require_bot(active_store, name)
        return _bot_payload(bot)

    @app.patch("/api/bots/{name}")
    async def update_bot(name: str, body: UpdateBotBody) -> dict[str, Any]:
        """Reconfigure a bot in place; omitted fields are preserved."""
        bot = _require_bot(active_store, name)
        cwd = bot.cwd
        if body.cwd is not None and body.cwd != bot.cwd:
            cwd = _validate_working_directory(body.cwd)
        model = bot.model if body.model is None else body.model.strip()
        updated = Bot(
            name=bot.name,
            cwd=cwd,
            agent=bot.agent if body.agent is None else body.agent.strip(),
            model=model,
            effort=bot.effort if body.effort is None else body.effort.strip(),
            engine=bot.engine,
            mcp_servers=bot.mcp_servers,
            brief=bot.brief if body.brief is None else body.brief.strip(),
        )
        active_store.put_bot(updated)
        applied_live = False
        if body.model is not None and model != bot.model:
            switch = getattr(active_engine, "set_bot_model", None)
            if switch is not None:
                try:
                    result = await _maybe_await(switch(name, model))
                    applied_live = bool(result.get("applied_live")) if isinstance(result, dict) else False
                except KeyError:
                    applied_live = False
        _publish_roster("bots", "updated", updated.name)
        return {**_bot_payload(updated), "applied_live": applied_live}

    @app.get("/api/directories")
    async def list_directories(path: str = Query(default="")) -> dict[str, Any]:
        current = _validate_working_directory(path or str(Path.home()))
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError as exc:
            raise HTTPException(status_code=422, detail="directory is not readable") from exc
        entries: list[dict[str, Any]] = []
        for child in children:
            if child.name.startswith("."):
                continue
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            try:
                has_git = (child / ".git").exists()
            except OSError:
                has_git = False
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "has_git": has_git,
                }
            )
            if len(entries) >= 500:
                break
        parent = current.parent
        return {
            "path": str(current),
            "parent": str(parent) if parent != current else "",
            "entries": entries,
        }

    @app.get("/api/engines/{engine}/models")
    async def engine_models(engine: str) -> dict[str, Any]:
        try:
            models = await asyncio.to_thread(providers.models_for, engine)
        except providers.ProviderError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"engine": engine, "models": models}

    @app.post("/api/bots/{name}/model")
    async def set_bot_model(name: str, body: BotModelBody) -> dict[str, Any]:
        _require_bot(active_store, name)
        switch = getattr(active_engine, "set_bot_model", None)
        if switch is None:
            bot = active_store.get_bot(name)
            assert bot is not None
            active_store.put_bot(
                Bot(
                    name=bot.name,
                    cwd=bot.cwd,
                    agent=bot.agent,
                    model=body.model.strip(),
                    effort=bot.effort,
                    engine=bot.engine,
                    mcp_servers=bot.mcp_servers,
                    brief=bot.brief,
                )
            )
            _publish_roster("bots", "updated", name)
            return {"bot": name, "model": body.model.strip(), "applied_live": False}
        try:
            result = await _maybe_await(switch(name, body.model))
        except KeyError:
            raise HTTPException(status_code=404, detail=f"bot {name!r} was not found")
        _publish_roster("bots", "updated", name)
        return {"bot": name, **_json_safe(result)}

    @app.get("/api/bots/{name}/card")
    async def bot_agent_card(name: str) -> dict[str, Any]:
        """A2A-style agent card: capability discovery for interoperable agents.

        Advertises what this bot is, what it can do, and how to task it, so
        external harnesses can discover and delegate without shared memory.
        """
        bot = _require_bot(active_store, name)
        skills: list[str] = []
        try:
            bindings = await asyncio.to_thread(active_plugins.binding_summaries, name)
            skills = sorted(
                {
                    str(item.get("plugin_id") or "")
                    for item in bindings
                    if item.get("plugin_id")
                }
            )
        except Exception:
            skills = []
        return _json_safe(
            {
                "name": bot.name,
                "description": bot.brief or f"{bot.engine} agent with durable memory",
                "engine": bot.engine,
                "model": bot.model,
                "skills": skills,
                "protocol": ["acp", "a2a-card/0.1"],
                "endpoints": {
                    "turns": f"/api/bots/{bot.name}/turns",
                    "runs": "/api/runs/{run_id}",
                    "handoff": f"/api/bots/{bot.name}/handoff",
                },
            }
        )

    @app.get("/api/bots/{name}/history")
    async def bot_history(name: str) -> dict[str, Any]:
        _require_bot(active_store, name)
        return {"bot": name, "turns": _json_safe(active_store.history(name))}

    @app.post("/api/bots/{name}/handoff")
    async def bot_handoff(name: str, body: HandoffBody) -> dict[str, Any]:
        _require_bot(active_store, name)
        try:
            bundle = await asyncio.to_thread(
                compile_handoff,
                active_store,
                name,
                to_engine=body.to_engine,
                budget_tokens=body.budget_tokens,
            )
        except HandoffError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _json_safe(bundle)

    @app.get("/api/bots/{name}/memory")
    async def bot_memory(
        name: str, limit: int = Query(default=100, ge=1, le=500)
    ) -> dict[str, Any]:
        _require_bot(active_store, name)
        events = await asyncio.to_thread(
            active_memory.list_events, name, limit=limit
        )
        return {"bot": name, "events": [event.summary() for event in events]}

    @app.get("/api/bots/{name}/memory/facts")
    async def list_memory_facts(
        name: str,
        q: str = Query(default=""),
        limit: int = Query(default=50, ge=1, le=500),
        include_invalid: bool = Query(default=False),
    ) -> dict[str, Any]:
        _require_bot(active_store, name)
        if q.strip():
            facts = await asyncio.to_thread(
                active_memory.retrieve_facts, name, q.strip(), limit=limit
            )
        else:
            facts = await asyncio.to_thread(
                active_memory.list_facts, name, include_invalid=include_invalid, limit=limit
            )
        return {"bot": name, "facts": [fact.summary() for fact in facts]}

    @app.post("/api/bots/{name}/memory/facts", status_code=201)
    async def remember_memory_fact(name: str, body: MemoryFactBody) -> dict[str, Any]:
        _require_bot(active_store, name)
        try:
            fact = await asyncio.to_thread(
                active_memory.remember,
                name,
                body.fact,
                entities=body.entities,
                source=body.source,
                actor=body.actor or "api",
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _json_safe(fact.summary())

    @app.post("/api/bots/{name}/memory/facts/{fact_id}/supersede")
    async def supersede_memory_fact(
        name: str, fact_id: str, body: MemorySupersedeBody
    ) -> dict[str, Any]:
        _require_bot(active_store, name)
        try:
            fact = await asyncio.to_thread(
                active_memory.supersede_fact,
                fact_id,
                body.fact,
                entities=body.entities,
                source=body.source,
                actor=body.actor or "api",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _json_safe(fact.summary())

    @app.post("/api/bots/{name}/memory/facts/{fact_id}/forget")
    async def forget_memory_fact(name: str, fact_id: str) -> dict[str, Any]:
        _require_bot(active_store, name)
        try:
            fact = await asyncio.to_thread(active_memory.forget_fact, fact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _json_safe(fact.summary())

    @app.post("/api/bots/{name}/memory/facts/{fact_id}/pin")
    async def pin_memory_fact(name: str, fact_id: str, body: MemoryPinBody) -> dict[str, Any]:
        _require_bot(active_store, name)
        try:
            fact = await asyncio.to_thread(
                active_memory.pin_fact, fact_id, bool(body.pinned)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _json_safe(fact.summary())

    _DREAM_ROUTINE_NAME = "nightly dreaming"
    _DREAM_PROMPT = (
        "Dreaming turn: consolidate your memory while the operator sleeps. "
        "Review your recent turns and memory_search results, then: (1) record "
        "durable facts (decisions, preferences, lessons) with memory_remember, "
        "(2) supersede outdated facts by remembering the new one and forgetting "
        "the old, (3) forget trivia with memory_forget, (4) keep it tight — a "
        "handful of crisp facts beats a diary. Never record secrets, tokens, or "
        "anyone else's private data. Reply with a short bullet list of what you "
        "kept, updated, or dropped."
    )

    def _dream_summary(routine: Any) -> dict[str, Any]:
        return {
            "id": routine.id,
            "name": routine.name,
            "bot_name": routine.bot_name,
            "enabled": routine.enabled,
            "trigger_kind": routine.trigger_kind,
            "interval_seconds": routine.interval_seconds,
            "next_run_at": routine.next_run_at,
        }

    @app.post("/api/bots/{name}/memory/dream", status_code=201)
    async def dream_memory(name: str, body: DreamBody) -> dict[str, Any]:
        """Enable nightly dreaming: a scheduled turn that consolidates memory.

        The routine prompts the bot to review recent turns, distill durable
        facts via memory_remember, supersede outdated ones, and forget trivia
        via memory_forget. Idempotent per bot — re-enabling returns the
        existing dream routine.
        """
        bot = _require_bot(active_store, name)
        for routine in active_routines.list(bot_name=bot.name):
            if routine.name == _DREAM_ROUTINE_NAME and routine.enabled:
                return _json_safe(_dream_summary(routine))
        try:
            routine = active_routines.create(
                name=_DREAM_ROUTINE_NAME,
                bot_name=bot.name,
                prompt=_DREAM_PROMPT,
                trigger_kind="interval",
                interval_seconds=body.interval_seconds,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _json_safe(_dream_summary(routine))

    @app.get("/api/bots/{name}/policy")
    async def get_policy(name: str) -> dict[str, Any]:
        _require_bot(active_store, name)
        return _json_safe(active_governance.get_policy(name))

    @app.put("/api/bots/{name}/policy")
    async def put_policy(name: str, body: PolicyBody) -> dict[str, Any]:
        _require_bot(active_store, name)
        try:
            current = active_governance.get_policy(name)
            policy = Policy(
                approval_mode=body.approval_mode if body.approval_mode is not None else current.approval_mode,  # type: ignore[arg-type]
                allowed_tools=tuple(body.allowed_tools) if body.allowed_tools is not None else current.allowed_tools,
                denied_tools=tuple(body.denied_tools) if body.denied_tools is not None else current.denied_tools,
                max_turns_per_hour=body.max_turns_per_hour if body.max_turns_per_hour is not None else current.max_turns_per_hour,
                max_concurrent_runs=body.max_concurrent_runs if body.max_concurrent_runs is not None else current.max_concurrent_runs,
                max_daily_runs=body.max_daily_runs if body.max_daily_runs is not None else current.max_daily_runs,
                auto_failover=body.auto_failover if body.auto_failover is not None else current.auto_failover,
                failover_engines=tuple(body.failover_engines) if body.failover_engines is not None else current.failover_engines,
            )
            return _json_safe(active_governance.set_policy(name, policy))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/bots/{name}/usage")
    async def bot_usage(
        name: str, limit: int = Query(default=50, ge=1, le=500)
    ) -> dict[str, Any]:
        """Aggregate ACP usage snapshots for a bot.

        ACP semantics: per session, ``used`` is the tokens currently in the
        context window (a snapshot, NOT a consumption counter) and ``cost`` is
        the cumulative session spend. Snapshots repeat every turn, so summing
        them would double count — we take the LAST snapshot per session and
        report the max across the bot's sessions.
        """
        _require_bot(active_store, name)
        turns = await asyncio.to_thread(active_store.history, name, limit)
        last_tokens_per_session: dict[str, int] = {}
        last_cost_per_session: dict[str, float] = {}
        for turn in turns:
            session_key = str(turn.get("session_id") or turn.get("id") or "")
            for event in turn.get("events", []):
                raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
                update = ((raw.get("params") or {}).get("update") or {})
                if update.get("sessionUpdate") != "usage_update":
                    continue
                try:
                    tokens = int(update.get("used") or 0)
                    cost = float((update.get("cost") or {}).get("amount") or 0)
                except (TypeError, ValueError):
                    continue
                # Chronological history: the last snapshot per session wins.
                last_tokens_per_session[session_key] = tokens
                last_cost_per_session[session_key] = cost
        tokens = max(last_tokens_per_session.values(), default=0)
        cost = max(last_cost_per_session.values(), default=0.0)
        return {
            "bot": name,
            "turns": len(turns),
            "sessions": len(last_tokens_per_session),
            "tokens": tokens,
            "tokens_in_context": tokens,
            "cost": {"amount": round(cost, 4), "currency": "USD"},
        }

    @app.post("/api/bots/{name}/turns", status_code=202)
    async def submit_turn(name: str, body: TurnBody) -> dict[str, Any]:
        _require_bot(active_store, name)
        run = await _maybe_await(active_engine.submit(name, body.message))
        run_id = _run_id(run)
        if not run_id:
            raise RuntimeError("engine.submit returned no run identifier")
        return {"run_id": run_id}

    @app.post("/api/bots/{name}/turns/{turn_id}/retry", status_code=202)
    async def retry_turn(name: str, turn_id: int, body: RetryBody) -> dict[str, Any]:
        """Re-run a durable turn, verbatim or with an edited prompt.

        Operator-initiated (UI button), so the delegation guardrail does not
        apply: the human explicitly asked for this run.
        """
        bot = _require_bot(active_store, name)
        turn = await asyncio.to_thread(active_store.get_turn, turn_id)
        if turn is None or str(turn.get("bot_name") or "") != bot.name:
            raise HTTPException(status_code=404, detail="turn was not found for this bot")
        message = body.message.strip() if body.message is not None else str(turn.get("prompt") or "")
        if not message:
            raise HTTPException(status_code=422, detail="turn has no prompt to retry")
        run = await _maybe_await(active_engine.submit(bot.name, message))
        run_id = _run_id(run)
        if not run_id:
            raise RuntimeError("engine.submit returned no run identifier")
        return {"run_id": run_id, "turn_id": turn_id, "retried": True}

    @app.post("/api/bots/{name}/turns/{turn_id}/fork", status_code=202)
    async def fork_turn(name: str, turn_id: int, body: ForkBody) -> dict[str, Any]:
        """Continue a turn on another bot, carrying a handoff bundle.

        Compiles the source bot's durable context (objective, memory, salient
        events, workspace reality) plus this turn's original request, and
        submits it as a fresh run on the target bot — e.g. escalate a stuck
        review to a stronger engine. Operator-initiated; no guardrail applies.
        """
        source = _require_bot(active_store, name)
        target = _require_bot(active_store, body.to_bot.strip())
        if target.name == source.name:
            raise HTTPException(status_code=422, detail="fork needs a different bot; use retry")
        turn = await asyncio.to_thread(active_store.get_turn, turn_id)
        if turn is None or str(turn.get("bot_name") or "") != source.name:
            raise HTTPException(status_code=404, detail="turn was not found for this bot")
        try:
            bundle = await asyncio.to_thread(
                compile_handoff,
                active_store,
                source.name,
                to_engine=target.engine,
                budget_tokens=body.budget_tokens,
            )
            context = str(bundle["prompt"])
        except HandoffError:
            # Source bot lives outside a git repo (or has thin history): fall
            # back to recent turn text instead of refusing the fork.
            recent = await asyncio.to_thread(active_store.history, source.name, 5)
            chunks: list[str] = []
            for recent_turn in recent:
                texts = [
                    str(event.get("text") or "")
                    for event in recent_turn.get("events", [])
                    if str(event.get("kind") or "") == "text"
                    and str(event.get("text") or "").strip()
                ]
                if texts:
                    chunks.append(
                        f"[{recent_turn.get('prompt') or 'earlier turn'}]\n"
                        + "\n".join(texts)
                    )
            context = "Recent context from {}:\n{}".format(
                source.name, "\n\n".join(chunks)[:8000] or "(no text recorded)"
            )
        prompt = str(turn.get("prompt") or "")
        message = (
            f"{context}\n\n<forked_request>\n"
            f"Continue this specific request on {target.name}:\n{prompt}\n"
            "</forked_request>"
        )
        run = await _maybe_await(active_engine.submit(target.name, message))
        run_id = _run_id(run)
        if not run_id:
            raise RuntimeError("engine.submit returned no run identifier")
        return {"run_id": run_id, "turn_id": turn_id, "to_bot": target.name}

    @app.post("/api/control/authorize")
    async def authorize_control_tool(body: AuthorizeBody) -> dict[str, Any]:
        """Hard delegation guardrail for bot-initiated coordination tools.

        The kiro-control and kyn-fleet MCP servers call this before executing
        any coordination-class tool (team plans, bot-to-bot calls, fleet admin).
        Humans (UI, CLI, API) never pass through here and are never gated.

        Fail-closed: an unattributable call (no active run for the caller) is
        denied, because an unscoped delegation can never be proven explicit.
        """
        caller = body.caller.strip()
        tool = body.tool.strip()
        if tool not in DELEGATION_GATED_TOOLS:
            return {"allowed": True, "reason": ""}
        bot_names = [bot.name for bot in active_store.list_bots()]
        lookup = getattr(active_engine, "active_run_for", None)
        snapshot = lookup(caller) if callable(lookup) else None
        if not isinstance(snapshot, dict):
            _logger.warning("Delegation denied for %r: no active run", caller)
            return {
                "allowed": False,
                "reason": (
                    f"No active turn is attributed to {caller!r}, so this "
                    "delegation cannot be tied to an explicit operator request. "
                    "Do the work in the current turn instead."
                ),
            }
        allowed, reason = authorize_delegation_tool(
            caller,
            tool,
            actor=str(snapshot.get("actor") or ""),
            message=str(snapshot.get("message") or ""),
            bot_names=bot_names,
            trusted_channel=_channel_senders_allowlisted(
                active_channels, str(snapshot.get("actor") or "")
            ),
        )
        if not allowed:
            _logger.warning(
                "Delegation denied for %r: %s(%s)", caller, tool, snapshot.get("actor")
            )
        return {"allowed": allowed, "reason": reason}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str, after: int = Query(default=0, ge=0)) -> dict[str, Any]:
        run = await _require_run(active_engine, run_id)
        payload = _json_safe(run)
        if isinstance(payload, dict):
            events = payload.get("events")
            if isinstance(events, list) and after:
                kept: list[dict[str, Any]] = []
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    try:
                        sequence = int(event.get("sequence") or 0)
                    except (TypeError, ValueError):
                        # Corrupt or foreign event shape: keep it rather than
                        # 500ing the whole poll window.
                        kept.append(event)
                        continue
                    if sequence > after:
                        kept.append(event)
                payload["events"] = kept
            return payload
        return {"run": payload}

    @app.get("/api/runs")
    async def list_runs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        listing = getattr(active_engine, "list_runs", None)
        if listing is None:
            return []
        return _json_safe(await _maybe_await(listing(limit=limit)))

    @app.post("/api/runs/{run_id}/permissions/{request_id}")
    async def decide_permission(run_id: str, request_id: str, body: PermissionBody) -> dict[str, Any]:
        await _require_run(active_engine, run_id)
        decision = body.decision.strip()
        if decision not in _PERMISSION_DECISIONS:
            raise HTTPException(status_code=422, detail="decision must be once or reject")
        try:
            result = await _maybe_await(active_engine.decide_permission(run_id, request_id, decision))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} was not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail="permission request is not actionable") from exc
        return {"run_id": run_id, "request_id": request_id, "decision": decision, "result": _json_safe(result)}

    @app.get("/api/interactions")
    async def list_interactions(
        bot_name: str | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        if bot_name is not None:
            _require_bot(active_store, bot_name)
        if status not in {None, "pending", "resolved", "expired"}:
            raise HTTPException(
                status_code=422,
                detail="status must be pending, resolved or expired",
            )
        return [
            item.summary()
            for item in active_interactions.list(
                bot_name=bot_name,
                status=status,  # type: ignore[arg-type]
                limit=limit,
            )
        ]

    @app.post("/api/interactions/{interaction_id}/decide")
    async def decide_interaction(
        interaction_id: str, body: PermissionBody, request: Request
    ) -> dict[str, Any]:
        decision = body.decision.strip()
        if decision not in _PERMISSION_DECISIONS:
            raise HTTPException(status_code=422, detail="decision must be once or reject")
        interaction = active_interactions.require(interaction_id)
        if interaction.status != "pending":
            if interaction.decision == decision:
                return interaction.summary()
            raise InteractionConflict("interaction has already been resolved")
        try:
            await _maybe_await(
                active_engine.decide_permission(
                    interaction.run_id,
                    interaction.request_id,
                    decision,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run was not found") from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409, detail="interaction is no longer actionable"
            ) from exc
        actor = request.headers.get("x-kiro-actor", "control-room")[:300]
        return active_interactions.resolve(
            interaction_id, decision, actor=actor
        ).summary()

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        await _require_run(active_engine, run_id)
        try:
            result = await _maybe_await(active_engine.cancel(run_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} was not found") from exc
        return {"run_id": run_id, "cancelled": True, "result": _json_safe(result)}

    @app.get("/api/routines")
    async def list_routines(bot_name: str | None = None) -> list[dict[str, Any]]:
        if bot_name is not None:
            _require_bot(active_store, bot_name)
        return [_json_safe(routine) for routine in active_routines.list(bot_name=bot_name)]

    @app.post("/api/routines", status_code=201)
    async def create_routine(body: CreateRoutineBody) -> dict[str, Any]:
        _require_bot(active_store, body.bot_name)
        try:
            routine = active_routines.create(
                name=body.name,
                bot_name=body.bot_name,
                prompt=body.prompt,
                trigger_kind=body.trigger_kind,  # type: ignore[arg-type]
                interval_seconds=body.interval_seconds,
                run_at=body.run_at,
                enabled=body.enabled,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _json_safe(routine)

    @app.patch("/api/routines/{routine_id}")
    async def update_routine(routine_id: str, body: UpdateRoutineBody) -> dict[str, Any]:
        changes = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
        if "bot_name" in changes:
            _require_bot(active_store, str(changes["bot_name"]))
        try:
            return _json_safe(active_routines.update(routine_id, **changes))
        except RoutineNotFound as exc:
            raise HTTPException(status_code=404, detail="routine was not found") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/routines/{routine_id}")
    async def delete_routine(routine_id: str) -> dict[str, Any]:
        if not active_routines.delete(routine_id):
            raise HTTPException(status_code=404, detail="routine was not found")
        return {"deleted": True, "id": routine_id}

    @app.get("/api/plugins")
    async def list_plugins() -> list[dict[str, Any]]:
        return [
            item
            for item in active_plugins.plugin_summaries()
            if item.get("id") != CONTROL_PLUGIN_ID
        ]

    @app.post("/api/plugins", status_code=201)
    async def create_plugin(body: CreatePluginBody) -> dict[str, Any]:
        if body.id == CONTROL_PLUGIN_ID:
            raise HTTPException(status_code=409, detail="plugin id is reserved")
        plugin = active_plugins.create_plugin(
            plugin_id=body.id,
            name=body.name,
            transport=body.transport,
            command=body.command,
            args=body.args,
            url=body.url,
            env=body.env,
            enabled=body.enabled,
        )
        return plugin.summary()

    @app.delete("/api/plugins/{plugin_id}")
    async def delete_plugin(plugin_id: str) -> dict[str, Any]:
        if plugin_id == CONTROL_PLUGIN_ID:
            raise HTTPException(status_code=409, detail="plugin is managed by Ari")
        active_plugins.delete_plugin(plugin_id)
        return {"deleted": True, "id": plugin_id}

    @app.get("/api/bots/{name}/plugins")
    async def list_bot_plugins(name: str) -> list[dict[str, Any]]:
        _require_bot(active_store, name)
        return [
            item
            for item in active_plugins.binding_summaries(name)
            if item.get("plugin_id") != CONTROL_PLUGIN_ID
        ]

    @app.put("/api/bots/{name}/plugins/{plugin_id}")
    async def bind_plugin(name: str, plugin_id: str, body: BindPluginBody) -> dict[str, Any]:
        _require_bot(active_store, name)
        if plugin_id == CONTROL_PLUGIN_ID:
            raise HTTPException(status_code=409, detail="plugin is managed by Ari")
        binding = active_plugins.bind_plugin(
            name,
            plugin_id,
            enabled=body.enabled,
            allow_tools=body.allow_tools,
            deny_tools=body.deny_tools,
            auto_approve_tools=body.auto_approve_tools,
            timeout_ms=body.timeout_ms,
        )
        return binding.summary()

    @app.delete("/api/bots/{name}/plugins/{plugin_id}")
    async def unbind_plugin(name: str, plugin_id: str) -> dict[str, Any]:
        _require_bot(active_store, name)
        if plugin_id == CONTROL_PLUGIN_ID:
            raise HTTPException(status_code=409, detail="plugin is managed by Ari")
        active_plugins.unbind_plugin(name, plugin_id)
        return {"deleted": True, "bot_name": name, "plugin_id": plugin_id}

    @app.get("/api/plugin-place/catalog")
    async def plugin_place_catalog() -> list[dict[str, Any]]:
        """Curated MCP servers with install + secret status."""
        return _json_safe(catalog_view(active_plugins))

    @app.post("/api/plugin-place/install", status_code=201)
    async def plugin_place_install(body: InstallPlaceBody) -> dict[str, Any]:
        """Install a catalog template and bind it to bots in ask mode."""
        for name in body.bot_names:
            _require_bot(active_store, name)
        try:
            result = await asyncio.to_thread(
                install_template,
                active_plugins,
                active_store,
                body.template_id.strip(),
                [name.strip() for name in body.bot_names],
                dict(body.config),
            )
        except PlaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _json_safe(result)

    @app.get("/api/plugins/{plugin_id}/secrets")
    async def list_plugin_secrets(plugin_id: str) -> dict[str, Any]:
        """Secret NAMES only — values never leave the vault over the API."""
        try:
            names = await asyncio.to_thread(active_plugins.secret_names, plugin_id)
        except PluginNotFoundError as exc:
            raise HTTPException(status_code=404, detail="plugin was not found") from exc
        return {"plugin_id": plugin_id, "secrets": names}

    @app.post("/api/plugins/{plugin_id}/secrets", status_code=201)
    async def set_plugin_secret(plugin_id: str, body: PluginSecretBody) -> dict[str, Any]:
        try:
            await asyncio.to_thread(
                active_plugins.set_secret, plugin_id, body.name, body.value
            )
        except PluginNotFoundError as exc:
            raise HTTPException(status_code=404, detail="plugin was not found") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"plugin_id": plugin_id, "name": body.name.strip(), "stored": True}

    @app.delete("/api/plugins/{plugin_id}/secrets/{name}")
    async def delete_plugin_secret(plugin_id: str, name: str) -> dict[str, Any]:
        try:
            deleted = await asyncio.to_thread(
                active_plugins.delete_secret, plugin_id, name
            )
        except PluginNotFoundError as exc:
            raise HTTPException(status_code=404, detail="plugin was not found") from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="secret was not found")
        return {"plugin_id": plugin_id, "deleted": True}

    @app.get("/api/audit")
    async def list_audit(
        bot_name: str | None = None,
        run_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        before_id: int | None = Query(default=None, ge=1),
    ) -> list[dict[str, Any]]:
        if bot_name is not None:
            _require_bot(active_store, bot_name)
        return active_governance.list_audit(
            bot_name=bot_name,
            run_id=run_id,
            limit=limit,
            before_id=before_id,
        )

    @app.get("/api/delegations")
    async def list_delegations() -> list[dict[str, Any]]:
        return [_json_safe(plan) for plan in active_delegations.list_plans()]

    @app.post("/api/delegations", status_code=201)
    async def create_delegation(body: CreateDelegationBody) -> dict[str, Any]:
        for node in body.nodes:
            _require_bot(active_store, node.bot_name)
        try:
            plan = active_delegations.create_plan(
                name=body.name,
                nodes=[
                    NodeSpec(id=node.id, bot_name=node.bot_name, prompt=node.prompt)
                    for node in body.nodes
                ],
                edges=[EdgeSpec(source=edge.source, target=edge.target) for edge in body.edges],
                max_fanout=body.max_fanout,
                max_depth=body.max_depth,
                start=body.start,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if body.start:
            launch_delegation(plan.id)
        return _delegation_payload(active_delegations, plan.id)

    @app.post("/api/delegations/{plan_id}/start")
    async def start_delegation(plan_id: str) -> dict[str, Any]:
        try:
            active_delegations.start_plan(plan_id)
        except PlanNotFound as exc:
            raise HTTPException(status_code=404, detail="delegation plan was not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        launch_delegation(plan_id)
        return _delegation_payload(active_delegations, plan_id)

    @app.get("/api/delegations/{plan_id}")
    async def get_delegation(plan_id: str) -> dict[str, Any]:
        if active_delegations.get_plan(plan_id) is None:
            raise HTTPException(status_code=404, detail="delegation plan was not found")
        return _delegation_payload(active_delegations, plan_id)

    @app.post("/api/delegations/{plan_id}/cancel")
    async def cancel_delegation(plan_id: str) -> dict[str, Any]:
        try:
            await active_delegation_coordinator.cancel_plan(plan_id)
        except PlanNotFound as exc:
            raise HTTPException(status_code=404, detail="delegation plan was not found") from exc
        return _delegation_payload(active_delegations, plan_id)

    @app.get("/api/workspaces")
    async def list_workspaces() -> list[dict[str, Any]]:
        return [manifest.summary() for manifest in active_workspaces.list_manifests()]

    @app.post("/api/workspaces", status_code=201)
    async def create_workspace(body: CreateWorkspaceBody) -> dict[str, Any]:
        if body.bot_name:
            _require_bot(active_store, body.bot_name)
        try:
            lease = await asyncio.to_thread(
                active_workspaces.create_workspace,
                body.repo_path,
                body.ref,
                body.run_id,
                bot_name=body.bot_name,
                lease_seconds=body.lease_seconds,
            )
        except WorkspaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _json_safe(lease)

    @app.get("/api/workspaces/{run_id}")
    async def get_workspace(run_id: str) -> dict[str, Any]:
        try:
            manifest = active_workspaces.get_manifest(run_id)
        except WorkspaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if manifest is None:
            raise HTTPException(status_code=404, detail="workspace was not found")
        return manifest.summary()

    @app.post("/api/workspaces/{run_id}/finalize")
    async def finalize_workspace(run_id: str, body: FinalizeWorkspaceBody) -> dict[str, Any]:
        lease = _workspace_lease(active_workspaces, run_id, body.token)
        try:
            manifest = await asyncio.to_thread(
                active_workspaces.finalize,
                lease,
                body.outcome,
                artifact_paths=body.artifact_paths,
            )
        except WorkspaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return manifest.summary()

    @app.post("/api/workspaces/{run_id}/cleanup")
    async def cleanup_workspace(run_id: str, body: WorkspaceLeaseBody) -> dict[str, Any]:
        lease = _workspace_lease(active_workspaces, run_id, body.token)
        try:
            manifest = await asyncio.to_thread(active_workspaces.cleanup_workspace, lease)
        except WorkspaceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return manifest.summary()

    @app.get("/api/coding-executions")
    async def list_coding_executions() -> list[dict[str, Any]]:
        return await active_coding_controller.list()

    @app.post("/api/coding-executions", status_code=202)
    async def create_coding_execution(
        body: CreateCodingExecutionBody,
    ) -> dict[str, Any]:
        _require_bot(active_store, body.builder_bot)
        _require_bot(active_store, body.reviewer_bot)
        try:
            spec = CodingExecutionSpec(
                repo_path=str(_validate_working_directory(body.repo_path)),
                ref=body.ref,
                task=body.task,
                builder_bot=body.builder_bot,
                reviewer_bot=body.reviewer_bot,
                checks=tuple(
                    CheckSpec(check.name, tuple(check.argv), check.timeout_seconds)
                    for check in body.checks
                ),
                max_repairs=body.max_repairs,
                timeout_seconds=body.timeout_seconds,
            )
            return await active_coding_controller.submit(
                spec, idempotency_key=body.idempotency_key
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/coding-executions/{execution_id}")
    async def get_coding_execution(execution_id: str) -> dict[str, Any]:
        try:
            return await active_coding_controller.get(execution_id)
        except CodingExecutionNotFound as exc:
            raise HTTPException(status_code=404, detail="coding execution was not found") from exc

    @app.post("/api/coding-executions/{execution_id}/approve")
    async def approve_coding_execution(
        execution_id: str, body: CodingHandoffBody
    ) -> dict[str, Any]:
        try:
            return await active_coding_controller.approve(
                execution_id, body.expected_version
            )
        except CodingExecutionNotFound as exc:
            raise HTTPException(status_code=404, detail="coding execution was not found") from exc

    @app.post("/api/coding-executions/{execution_id}/cancel")
    async def cancel_coding_execution(execution_id: str) -> dict[str, Any]:
        try:
            return await active_coding_controller.cancel(execution_id)
        except CodingExecutionNotFound as exc:
            raise HTTPException(status_code=404, detail="coding execution was not found") from exc

    def _task_view(execution: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        spec = execution.get("spec") or {}
        result = execution.get("result") or {}
        records = result.get("records") or []
        latest_checks: dict[str, dict[str, Any]] = {}
        for record in records:
            command = record.get("command") or {}
            check_name = str(command.get("label") or "")
            if not check_name:
                continue
            command_result = record.get("result") or {}
            exit_code = command_result.get("exit_code")
            latest_checks[check_name] = {
                "status": (
                    "timeout" if command_result.get("timed_out")
                    else "passed" if exit_code == 0
                    else "failed" if exit_code is not None
                    else "unknown"
                ),
                "duration_seconds": command_result.get("duration_seconds"),
            }
        checks = [
            {
                "name": str(check.get("name") or "Check"),
                **latest_checks.get(str(check.get("name") or ""), {"status": "pending"}),
            }
            for check in spec.get("checks") or []
        ]
        review = result.get("review") or {}
        repo = str(task.get("repo_path") or "")
        branch = str(task.get("branch") or "")
        state = derive_task_state(repo, branch, str(execution.get("id") or ""))
        return {
            "id": execution.get("id"),
            "status": execution.get("status"),
            "task_status": state,
            "version": execution.get("version"),
            "builder_bot": spec.get("builder_bot"),
            "reviewer_bot": spec.get("reviewer_bot"),
            "repo_path": repo,
            "branch": branch,
            "base": task.get("base"),
            "task": spec.get("task"),
            "error": execution.get("error"),
            "created_at": task.get("created_at"),
            "updated_at": execution.get("updated_at"),
            "finished_at": execution.get("finished_at"),
            "checks": checks,
            "review": {
                "approved": review.get("approved"),
                "summary": review.get("summary"),
                "findings": review.get("findings") or [],
                "blocking_findings": review.get("blocking_findings") or [],
            } if review else None,
        }

    async def _require_task(execution_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            execution = await active_coding_controller.get(execution_id)
        except CodingExecutionNotFound as exc:
            raise HTTPException(status_code=404, detail="task was not found") from exc
        task = await asyncio.to_thread(active_tasks.get_task, execution_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task was not found")
        return execution, task

    @app.post("/api/tasks", status_code=202)
    async def create_task(body: CreateTaskBody) -> dict[str, Any]:
        """Start a reviewable task: branch + isolated build + review gates.

        Pins ``base`` to a commit, creates ``kyn/task-<key>`` there, then runs
        the standard coding lifecycle detached at the branch tip (deterministic
        — the branch cannot move under the run). Nothing merges without review.
        """
        _require_bot(active_store, body.builder_bot)
        _require_bot(active_store, body.reviewer_bot)
        key = uuid.uuid4().hex[:12]
        branch = f"kyn/task-{key}"
        try:
            repo = str(_validate_working_directory(body.repo_path))
            base = await asyncio.to_thread(resolve_base, repo, body.base)
            base_commit = await asyncio.to_thread(resolve_commit, repo, base)
            await asyncio.to_thread(create_task_branch, repo, branch, base_commit)
            spec = CodingExecutionSpec(
                repo_path=repo,
                ref=branch,
                task=body.task,
                builder_bot=body.builder_bot,
                reviewer_bot=body.reviewer_bot,
                checks=tuple(
                    CheckSpec(check.name, tuple(check.argv), check.timeout_seconds)
                    for check in body.checks
                ),
                max_repairs=body.max_repairs,
                timeout_seconds=body.timeout_seconds,
            )
        except (TypeError, ValueError, TaskError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            snapshot = await active_coding_controller.submit(
                spec, idempotency_key=f"task-{key}"
            )
        except CodingExecutionConflict as exc:
            await asyncio.to_thread(delete_task_branch, repo, branch, force=True)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (TypeError, ValueError, CodingLifecycleError) as exc:
            await asyncio.to_thread(delete_task_branch, repo, branch, force=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        adopted = str(snapshot.get("id") or "")
        if not adopted:
            await asyncio.to_thread(delete_task_branch, repo, branch, force=True)
            raise RuntimeError("coding controller returned no execution identifier")
        task = await asyncio.to_thread(active_tasks.add_task, adopted, repo, branch, base)
        execution = await active_coding_controller.get(adopted)
        return _json_safe(_task_view(execution, task))

    @app.get("/api/tasks")
    async def list_tasks() -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(active_tasks.list_tasks)
        views: list[dict[str, Any]] = []
        for row in rows:
            try:
                execution = await active_coding_controller.get(str(row["execution_id"]))
            except CodingExecutionNotFound:
                continue
            views.append(_task_view(execution, row))
        return _json_safe(views)

    @app.get("/api/tasks/{execution_id}")
    async def get_task(execution_id: str) -> dict[str, Any]:
        execution, task = await _require_task(execution_id)
        view = _task_view(execution, task)
        worktree = await _task_worktree(execution_id)
        view["worktree_path"] = worktree
        if worktree is None:
            view["files"] = []
        else:
            try:
                view["files"] = list((await asyncio.to_thread(worktree_diff, worktree)).files)
            except TaskError:
                view["files"] = []
        return _json_safe(view)

    @app.get("/api/tasks/{execution_id}/diff")
    async def task_diff(execution_id: str) -> dict[str, Any]:
        execution, task = await _require_task(execution_id)
        worktree = await _task_worktree(execution_id)
        if worktree is None:
            raise HTTPException(status_code=404, detail="task worktree is gone")
        try:
            diff = await asyncio.to_thread(worktree_diff, worktree)
        except TaskError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _json_safe(
            {
                "id": execution_id,
                "branch": task.get("branch"),
                "base": task.get("base"),
                "files": list(diff.files),
                "diff": diff.diff,
                "truncated": diff.truncated,
            }
        )

    @app.post("/api/tasks/{execution_id}/merge")
    async def merge_task(execution_id: str, body: MergeTaskBody) -> dict[str, Any]:
        """Merge reviewed task work into its base branch.

        Only reviewed work merges (execution ``awaiting_handoff``/``ready``).
        Commits the worktree, pushes ``HEAD:<branch>``, ``--no-ff`` merges
        into a clean checked-out base, then deletes the branch. Conflicts
        abort cleanly with a 409 listing the files.
        """
        execution, task = await _require_task(execution_id)
        if str(execution.get("status") or "") not in {"awaiting_handoff", "ready"}:
            raise HTTPException(
                status_code=409,
                detail="only reviewed work merges — approve the handoff first",
            )
        repo = str(task.get("repo_path") or "")
        branch = str(task.get("branch") or "")
        base = str(task.get("base") or "")
        worktree = await _task_worktree(execution_id)
        if worktree is None:
            raise HTTPException(status_code=404, detail="task worktree is gone")
        spec = execution.get("spec") or {}
        first_line = str(spec.get("task") or "").strip().splitlines()
        summary = first_line[0][:80] if first_line else "task work"
        marker = merge_marker(execution_id)
        try:
            committed = await asyncio.to_thread(
                commit_worktree, worktree, f"kyn task {execution_id}: {summary}"
            )
            if not committed:
                # Nothing changed in the worktree: is there anything to merge?
                # Compare branch tip against base tip.
                raise HTTPException(status_code=422, detail="no changes to merge")
            await asyncio.to_thread(push_to_branch, worktree, repo, branch)
            message = body.message.strip() if body.message else f"Merge {branch} ({marker}): {summary}"
            result = await asyncio.to_thread(
                merge_task_branch, repo, branch, base, f"{message}\n\n{marker}"
            )
        except HTTPException:
            raise
        except TaskConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TaskError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _json_safe({"id": execution_id, "merged": True, **result})

    @app.post("/api/tasks/{execution_id}/abandon")
    async def abandon_task(execution_id: str) -> dict[str, Any]:
        """Abandon a task: cancel the run, force-remove the worktree, delete the branch."""
        execution, task = await _require_task(execution_id)
        repo = str(task.get("repo_path") or "")
        branch = str(task.get("branch") or "")
        try:
            await active_coding_controller.cancel(execution_id)
        except (CodingExecutionNotFound, CodingLifecycleError):
            pass
        worktree = await _task_worktree(execution_id)
        if worktree is not None:
            try:
                await asyncio.to_thread(remove_worktree, worktree, force=True)
            except TaskError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            await asyncio.to_thread(delete_task_branch, repo, branch, force=True)
        except TaskError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _json_safe({"id": execution_id, "abandoned": True})

    async def _task_worktree(execution_id: str) -> str | None:
        manifest = await asyncio.to_thread(active_workspaces.get_manifest, execution_id)
        if manifest is None:
            return None
        return str(manifest.worktree_path or "") or None

    @app.get("/api/channels")
    async def list_channels(bot_name: str | None = None) -> list[dict[str, Any]]:
        if bot_name is not None:
            _require_bot(active_store, bot_name)
        return [binding.summary() for binding in active_channels.list_bindings(bot_name=bot_name)]

    @app.post("/api/channels", status_code=201)
    async def create_channel(body: CreateChannelBody) -> dict[str, Any]:
        _require_bot(active_store, body.bot_name)
        try:
            binding = active_channels.create_binding(
                binding_id=body.id,
                name=body.name,
                kind=body.kind,
                bot_name=body.bot_name,
                signing_secret_env=body.signing_secret_env,
                verify_token_env=body.verify_token_env,
                outbound_token_env=body.outbound_token_env,
                trigger_prefix=body.trigger_prefix,
                allowed_sources=body.allowed_sources,
                allowed_senders=body.allowed_senders,
                enabled=body.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return binding.summary()

    @app.patch("/api/channels/{binding_id}")
    async def update_channel(binding_id: str, body: UpdateChannelBody) -> dict[str, Any]:
        return active_channels.set_enabled(binding_id, body.enabled).summary()

    @app.delete("/api/channels/{binding_id}")
    async def delete_channel(binding_id: str) -> dict[str, Any]:
        if not active_channels.delete_binding(binding_id):
            raise ChannelNotFound(f"channel {binding_id!r} was not found")
        return {"deleted": True, "id": binding_id}

    @app.get("/api/channel-events")
    async def list_channel_events(
        binding_id: str | None = None,
        thread_key: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        if binding_id is not None:
            active_channels.require_binding(binding_id)
        return [
            event.snapshot()
            for event in active_channels.list_events(
                binding_id=binding_id, thread_key=thread_key, limit=limit
            )
        ]

    @app.get("/api/channel-events/{event_id}")
    async def get_channel_event(event_id: str) -> dict[str, Any]:
        event = active_channels.get_event(event_id)
        if event is None:
            raise ChannelNotFound(f"channel event {event_id!r} was not found")
        return event.snapshot()

    # ---- Group chats -----------------------------------------------------

    def _group_payload(group_id: str, *, after: int = 0, limit: int = 200) -> dict[str, Any]:
        group = active_groups.require_group(group_id)
        return {
            "group": group.summary(),
            "members": [_json_safe(_bot_payload(bot)) for bot in active_store.list_bots() if bot.name in group.members],
            "messages": [
                message.summary() for message in active_groups.messages(group_id, after=after, limit=limit)
            ],
            "running": active_group_coordinator.is_running(group_id),
            "speaking": active_group_coordinator.speaking(group_id),
            "context_note": active_groups.context_note(group_id),
        }

    @app.get("/api/groups")
    async def list_groups() -> list[dict[str, Any]]:
        return [
            {
                **group.summary(),
                "running": active_group_coordinator.is_running(group.id),
                "message_count": active_groups.count_messages(group.id),
            }
            for group in active_groups.list_groups()
        ]

    @app.post("/api/groups", status_code=201)
    async def create_group(body: CreateGroupBody) -> dict[str, Any]:
        for member in body.members:
            _require_bot(active_store, member)
        try:
            group = await asyncio.to_thread(
                active_groups.create_group,
                body.name,
                body.aim,
                body.members,
                max_rounds=body.max_rounds,
                reply_mode=body.reply_mode,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if body.start:
            await active_group_coordinator.start(group.id)
        _publish_roster("groups", "created", group.id)
        return _group_payload(group.id)

    @app.get("/api/groups/{group_id}")
    async def get_group(
        group_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> dict[str, Any]:
        return _group_payload(group_id, after=after, limit=limit)

    @app.post("/api/groups/{group_id}/messages", status_code=201)
    async def post_group_message(group_id: str, body: GroupMessageBody) -> dict[str, Any]:
        try:
            message = await active_group_coordinator.post_message(
                group_id, body.text, respond=body.respond, mentions=body.mentions
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _publish_roster("groups", "updated", group_id)
        return {"message": message.summary(), "group": _group_payload(group_id)}

    @app.put("/api/groups/{group_id}/context")
    async def set_group_context(group_id: str, body: GroupContextBody) -> dict[str, Any]:
        """Pin or clear the handoff brief every member of the group sees."""
        try:
            group = await asyncio.to_thread(active_groups.set_context_note, group_id, body.note)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _publish_roster("groups", "updated", group.id)
        return _group_payload(group.id)

    @app.put("/api/groups/{group_id}/mode")
    async def set_group_mode(group_id: str, body: GroupModeBody) -> dict[str, Any]:
        """Switch a group between sequential turns and parallel fan-out."""
        try:
            group = await asyncio.to_thread(active_groups.set_reply_mode, group_id, body.mode)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _publish_roster("groups", "updated", group.id)
        return _group_payload(group.id)

    @app.post("/api/groups/{group_id}/start")
    async def start_group(group_id: str, rounds: int | None = Query(default=None, ge=1, le=10)) -> dict[str, Any]:
        try:
            await active_group_coordinator.start(group_id, rounds=rounds)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _publish_roster("groups", "updated", group_id)
        return _group_payload(group_id)

    @app.post("/api/groups/{group_id}/stop")
    async def stop_group(group_id: str) -> dict[str, Any]:
        await active_group_coordinator.stop(group_id)
        _publish_roster("groups", "updated", group_id)
        return _group_payload(group_id)

    @app.delete("/api/groups/{group_id}")
    async def delete_group(group_id: str) -> dict[str, Any]:
        active_groups.require_group(group_id)
        if active_group_coordinator.is_running(group_id):
            await active_group_coordinator.stop(group_id)
        if not active_groups.delete_group(group_id):
            raise GroupNotFound(group_id)
        _publish_roster("groups", "deleted", group_id)
        return {"deleted": True, "id": group_id}

    @app.post("/hooks/slack/{binding_id}")
    async def ingest_slack(binding_id: str, request: Request) -> Any:
        binding = _hook_binding(active_channels, binding_id, kind="slack")
        raw = await request.body()
        verify_slack(
            raw,
            request.headers.get("x-slack-request-timestamp", ""),
            request.headers.get("x-slack-signature", ""),
            resolve_secret(binding),
        )
        payload = _json_object(raw)
        if payload.get("type") == "url_verification":
            challenge = str(payload.get("challenge", ""))
            if not challenge:
                raise HTTPException(status_code=422, detail="Slack challenge is missing")
            return PlainTextResponse(challenge)
        incoming = slack_event(payload, binding)
        if incoming is None:
            return {"accepted": False, "ignored": True}
        event, created = await active_channel_gateway.ingest(binding, incoming)
        return {"accepted": True, "duplicate": not created, "event_id": event.id}

    @app.post("/hooks/github/{binding_id}")
    async def ingest_github(binding_id: str, request: Request) -> dict[str, Any]:
        binding = _hook_binding(active_channels, binding_id, kind="github")
        raw = await request.body()
        verify_sha256(
            raw, request.headers.get("x-hub-signature-256", ""), resolve_secret(binding)
        )
        event_type = request.headers.get("x-github-event", "")
        delivery_id = request.headers.get("x-github-delivery", "")
        if not delivery_id:
            raise HTTPException(status_code=422, detail="GitHub delivery ID is missing")
        if event_type == "ping":
            return {"accepted": False, "ignored": True, "pong": True}
        incoming = github_event(_json_object(raw), event_type, delivery_id, binding)
        if incoming is None:
            return {"accepted": False, "ignored": True}
        event, created = await active_channel_gateway.ingest(binding, incoming)
        return {"accepted": True, "duplicate": not created, "event_id": event.id}

    @app.get("/hooks/whatsapp/{binding_id}")
    async def verify_whatsapp(binding_id: str, request: Request) -> PlainTextResponse:
        binding = _hook_binding(active_channels, binding_id, kind="whatsapp")
        mode = request.query_params.get("hub.mode", "")
        supplied = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        expected = resolve_verify_token(binding)
        if mode != "subscribe" or not challenge or not hmac.compare_digest(supplied, expected):
            raise ChannelAuthorizationError("WhatsApp verification token is invalid")
        return PlainTextResponse(challenge)

    @app.post("/hooks/whatsapp/{binding_id}")
    async def ingest_whatsapp(binding_id: str, request: Request) -> dict[str, Any]:
        binding = _hook_binding(active_channels, binding_id, kind="whatsapp")
        raw = await request.body()
        verify_sha256(
            raw, request.headers.get("x-hub-signature-256", ""), resolve_secret(binding)
        )
        incoming_events = whatsapp_events(_json_object(raw))
        accepted: list[dict[str, Any]] = []
        for incoming in incoming_events:
            event, created = await active_channel_gateway.ingest(binding, incoming)
            accepted.append({"event_id": event.id, "duplicate": not created})
        return {
            "accepted": bool(accepted),
            "ignored": not accepted,
            "events": accepted,
        }

    @app.post("/hooks/email/{binding_id}")
    async def ingest_email(binding_id: str, request: Request) -> dict[str, Any]:
        binding = _hook_binding(active_channels, binding_id, kind="email")
        raw = await request.body()
        verify_kiro_webhook(
            raw,
            request.headers.get("x-kiro-timestamp", ""),
            request.headers.get("x-kiro-signature-256", ""),
            resolve_secret(binding),
        )
        event, created = await active_channel_gateway.ingest(
            binding, email_event(_json_object(raw))
        )
        return {"accepted": True, "duplicate": not created, "event_id": event.id}

    @app.post("/hooks/webhook/{binding_id}")
    async def ingest_generic_webhook(binding_id: str, request: Request) -> dict[str, Any]:
        binding = _hook_binding(active_channels, binding_id, kind="webhook")
        raw = await request.body()
        verify_kiro_webhook(
            raw,
            request.headers.get("x-kiro-timestamp", ""),
            request.headers.get("x-kiro-signature-256", ""),
            resolve_secret(binding),
        )
        event, created = await active_channel_gateway.ingest(
            binding, generic_event(_json_object(raw))
        )
        return {"accepted": True, "duplicate": not created, "event_id": event.id}

    @app.websocket("/ws/runs/{run_id}")
    async def stream_run(websocket: WebSocket, run_id: str, after: int = Query(default=0, ge=0)) -> None:
        if not await authorize_websocket(websocket):
            return
        if await _get_run(active_engine, run_id) is None:
            await websocket.close(code=4404, reason="run not found")
            return
        await websocket.accept()
        try:
            subscription = active_engine.subscribe(run_id, after)
            if inspect.isawaitable(subscription):
                subscription = await subscription
            async for event in subscription:
                await websocket.send_json(_json_safe(event))
            final_run = await _get_run(active_engine, run_id)
            await websocket.send_json(
                {"type": "terminal", "run_id": run_id, "run": _json_safe(final_run)}
            )
            await websocket.close(code=1000)
        except WebSocketDisconnect:
            return
        except Exception as exc:
            _logger.exception("Ari WebSocket stream failed", exc_info=exc)
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": "stream_failed",
                        "detail": "The live stream could not be completed",
                    }
                )
                await websocket.close(code=1011)
            except (WebSocketDisconnect, RuntimeError):
                return

    @app.websocket("/ws/live")
    async def stream_live(websocket: WebSocket) -> None:
        if not await authorize_websocket(websocket):
            return
        await websocket.accept()
        queue = active_live.subscribe()
        try:
            await websocket.send_json({"type": "hello"})
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                except TimeoutError:
                    await websocket.send_json({"type": "ping"})
                    continue
                await websocket.send_json(_json_safe(payload))
        except Exception:
            return
        finally:
            active_live.unsubscribe(queue)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/app/", status_code=307)

    packaged_web_dir = Path(__file__).resolve().parent / "web"
    development_web_dir = Path(__file__).resolve().parents[2] / "web"
    web_dir = packaged_web_dir if packaged_web_dir.is_dir() else development_web_dir
    built_web_dir = web_dir / "dist" if web_dir.is_dir() else None
    static_dir = built_web_dir if built_web_dir and built_web_dir.is_dir() else web_dir
    if static_dir.is_dir():
        app.mount("/app", StaticFiles(directory=static_dir, html=True), name="app")

    return app


def _make_engine(
    store: Store,
    governance: GovernanceStore,
    plugins: PluginRegistry,
    workspaces: WorkspaceManager,
    memory: SharedMemoryStore,
    interactions: InteractionStore,
) -> Any:
    try:
        from .engine import Engine
    except ImportError as exc:
        raise RuntimeError("The daemon engine is unavailable") from exc
    try:
        return Engine(
            store=store,
            governance=governance,
            plugins=plugins,
            workspaces=workspaces,
            memory=memory,
            interactions=interactions,
        )
    except TypeError:
        return Engine(store)


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="webhook body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="webhook body must be a JSON object")
    return payload


def _validate_bot_name(name: str) -> str:
    candidate = name.strip()
    if not _BOT_NAME.fullmatch(candidate):
        raise HTTPException(
            status_code=422,
            detail="name must start with a letter or number and contain only letters, numbers, '.', '_' or '-'",
        )
    return candidate


def _validate_working_directory(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        raise HTTPException(status_code=422, detail="cwd must be an absolute path")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail="cwd does not exist") from exc
    if not resolved.is_dir():
        raise HTTPException(status_code=422, detail="cwd must be a directory")
    return resolved


def _require_bot(store: Store, name: str) -> Bot:
    canonical = _validate_bot_name(name)
    bot = store.get_bot(canonical)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"bot {canonical!r} was not found")
    return bot


def _channel_senders_allowlisted(channels: Any, actor: str) -> bool:
    """Is this channel turn's text operator intent?

    Only a channel binding with a non-empty sender allowlist (personal
    devices) counts: anything else is multi-party, and a stranger's signed
    event must never authorize fleet administration.
    """
    if not actor.startswith("channel:"):
        return False
    parts = actor.split(":", 2)
    if len(parts) != 3:
        return False
    try:
        binding = channels.get_binding(parts[2])
    except Exception:
        return False
    return bool(binding is not None and binding.allowed_senders)


def _hook_binding(channels: Any, binding_id: str, *, kind: str) -> Any:
    """Resolve a webhook binding without leaking its existence.

    Missing/wrong-kind bindings raise the same 401 as a bad signature, so
    probing binding IDs through the public gateway cannot distinguish "no
    such binding" from "wrong secret".
    """
    try:
        return channels.require_binding(binding_id, kind=kind)
    except ChannelNotFound as exc:
        raise ChannelAuthenticationError("invalid channel signature") from exc


async def _get_run(engine: Any, run_id: str) -> Any:
    try:
        return await _maybe_await(engine.get_run(run_id))
    except KeyError:
        return None


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        converted = asdict(value)
        return converted if isinstance(converted, Mapping) else None
    attributes = getattr(value, "__dict__", None)
    return attributes if isinstance(attributes, Mapping) else None


async def _require_run(engine: Any, run_id: str) -> Any:
    run = await _get_run(engine, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} was not found")
    return run


def _run_id(run: Any) -> str:
    if isinstance(run, str):
        return run
    if isinstance(run, Mapping):
        return str(run.get("run_id") or run.get("id") or "")
    return str(getattr(run, "run_id", None) or getattr(run, "id", None) or "")


def _bot_payload(bot: Bot) -> dict[str, Any]:
    return {
        "name": bot.name,
        "cwd": bot.cwd,
        "agent": bot.agent,
        "model": bot.model,
        "effort": bot.effort,
        "engine": bot.engine,
        "brief": bot.brief,
        "mcp_servers": _json_safe(bot.mcp_servers or []),
    }


def _delegation_payload(service: DelegationStore, plan_id: str) -> dict[str, Any]:
    plan = service.get_plan(plan_id)
    if plan is None:
        raise PlanNotFound(plan_id)
    return {
        "plan": _json_safe(plan),
        "nodes": [_json_safe(node) for node in service.nodes(plan_id)],
        "edges": [_json_safe(edge) for edge in service.edges(plan_id)],
        "aggregation": _json_safe(service.aggregation(plan_id)),
    }


def _workspace_lease(
    service: WorkspaceManager,
    run_id: str,
    token: str,
) -> WorkspaceLease:
    manifest = service.get_manifest(run_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="workspace was not found")
    return WorkspaceLease(
        run_id=manifest.run_id,
        token=token,
        path=manifest.worktree_path,
        repo_path=manifest.repo_path,
        requested_ref=manifest.requested_ref,
        commit=manifest.commit,
        lease_expires_at=manifest.lease_expires_at,
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if hasattr(value, "dict"):
        return _json_safe(value.dict())
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    return str(value)
