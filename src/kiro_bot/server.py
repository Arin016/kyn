"""HTTP and WebSocket control plane for Kiro Bot.

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
from .run_store import RunRepository
from .routines import RoutineNotFound, RoutineStore, Scheduler
from .memory import SharedMemoryStore
from .internal_control import CONTROL_PLUGIN_ID, ensure_bot_control, ensure_internal_control
from .interactions import InteractionConflict, InteractionNotFound, InteractionStore
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


    class TurnBody(BaseModel):
        message: str = Field(min_length=1)


    class PermissionBody(BaseModel):
        decision: str = Field(min_length=1)


    class PolicyBody(BaseModel):
        approval_mode: str = "ask"
        allowed_tools: list[str] = Field(default_factory=list)
        denied_tools: list[str] = Field(default_factory=list)
        max_turns_per_hour: int = Field(default=0, ge=0)
        max_concurrent_runs: int = Field(default=0, ge=0)
        max_daily_runs: int = Field(default=0, ge=0)


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
            "Install kiro-bot with its server extra (for example: "
            "pip install 'kiro-bot[server]')."
        ) from _FASTAPI_IMPORT_ERROR

    active_store = store or Store()
    active_governance = governance or GovernanceStore(active_store)
    active_plugins = plugins or PluginRegistry(active_store)
    ensure_internal_control(active_store, active_plugins)
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
    active_coding_controller = coding_controller or CodingLifecycleController(
        active_coding_store, active_engine, active_workspaces
    )
    active_channels = channels or ChannelStore(active_store)
    active_live = live or LiveBus()

    async def engine_submit(bot_name: str, message: str, actor: str) -> object:
        submit = active_engine.submit
        try:
            parameters = inspect.signature(submit).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "actor" in parameters:
            return await _maybe_await(submit(bot_name, message, actor=actor))
        return await _maybe_await(submit(bot_name, message))

    async def scheduled_submit(bot_name: str, message: str) -> object:
        return await engine_submit(bot_name, message, "scheduler")

    async def delegated_submit(bot_name: str, message: str) -> str:
        return _run_id(await engine_submit(bot_name, message, "delegation"))

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
            active_interactions.list, status="pending", limit=500
        )
        return [item.summary() for item in items if item.run_id == run_id]

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

    active_scheduler = scheduler or Scheduler(active_routines, scheduled_submit)
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
            name=f"kiro-bot-delegation:{plan_id}",
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

    app = FastAPI(title="Kiro Bot", version="0.1.0", lifespan=lifespan)
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
    app.state.live = active_live

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "invalid_request", "detail": _json_safe(exc.errors())})

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        # Prompts, local paths and provider details can occur in exceptions.
        # Preserve those only in server logs, never in the wire response.
        _logger.exception("Unhandled Kiro Bot API error", exc_info=exc)
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

    @app.get("/api/bots")
    async def list_bots() -> list[dict[str, Any]]:
        return [_bot_payload(bot) for bot in active_store.list_bots()]

    @app.post("/api/bots", status_code=201)
    async def create_bot(body: CreateBotBody) -> dict[str, Any]:
        name = _validate_bot_name(body.name)
        cwd = _validate_working_directory(body.cwd)
        bot = Bot(
            name=name,
            cwd=str(cwd),
            agent=(body.agent or "").strip(),
            model=(body.model or "").strip(),
            effort=(body.effort or "").strip(),
        )
        active_store.put_bot(bot)
        ensure_bot_control(active_plugins, bot.name)
        return _bot_payload(bot)

    @app.get("/api/bots/{name}")
    async def get_bot(name: str) -> dict[str, Any]:
        bot = _require_bot(active_store, name)
        return _bot_payload(bot)

    @app.get("/api/bots/{name}/history")
    async def bot_history(name: str) -> dict[str, Any]:
        _require_bot(active_store, name)
        return {"bot": name, "turns": _json_safe(active_store.history(name))}

    @app.get("/api/bots/{name}/memory")
    async def bot_memory(
        name: str, limit: int = Query(default=100, ge=1, le=500)
    ) -> dict[str, Any]:
        _require_bot(active_store, name)
        events = await asyncio.to_thread(
            active_memory.list_events, name, limit=limit
        )
        return {"bot": name, "events": [event.summary() for event in events]}

    @app.get("/api/bots/{name}/policy")
    async def get_policy(name: str) -> dict[str, Any]:
        _require_bot(active_store, name)
        return _json_safe(active_governance.get_policy(name))

    @app.put("/api/bots/{name}/policy")
    async def put_policy(name: str, body: PolicyBody) -> dict[str, Any]:
        _require_bot(active_store, name)
        try:
            policy = Policy(
                approval_mode=body.approval_mode,  # type: ignore[arg-type]
                allowed_tools=tuple(body.allowed_tools),
                denied_tools=tuple(body.denied_tools),
                max_turns_per_hour=body.max_turns_per_hour,
                max_concurrent_runs=body.max_concurrent_runs,
                max_daily_runs=body.max_daily_runs,
            )
            return _json_safe(active_governance.set_policy(name, policy))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/bots/{name}/turns", status_code=202)
    async def submit_turn(name: str, body: TurnBody) -> dict[str, Any]:
        _require_bot(active_store, name)
        run = await _maybe_await(active_engine.submit(name, body.message))
        run_id = _run_id(run)
        if not run_id:
            raise RuntimeError("engine.submit returned no run identifier")
        return {"run_id": run_id}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str, after: int = Query(default=0, ge=0)) -> dict[str, Any]:
        run = await _require_run(active_engine, run_id)
        payload = _json_safe(run)
        if isinstance(payload, dict):
            events = payload.get("events")
            if isinstance(events, list) and after:
                payload["events"] = [
                    event
                    for event in events
                    if isinstance(event, dict) and int(event.get("sequence") or 0) > after
                ]
            return payload
        return {"run": payload}

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
            raise HTTPException(status_code=409, detail="plugin is managed by Kiro Bot")
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
            raise HTTPException(status_code=409, detail="plugin is managed by Kiro Bot")
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
            raise HTTPException(status_code=409, detail="plugin is managed by Kiro Bot")
        active_plugins.unbind_plugin(name, plugin_id)
        return {"deleted": True, "bot_name": name, "plugin_id": plugin_id}

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

    @app.post("/hooks/slack/{binding_id}")
    async def ingest_slack(binding_id: str, request: Request) -> Any:
        binding = active_channels.require_binding(binding_id, kind="slack")
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
        binding = active_channels.require_binding(binding_id, kind="github")
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
        binding = active_channels.require_binding(binding_id, kind="whatsapp")
        mode = request.query_params.get("hub.mode", "")
        supplied = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        expected = resolve_verify_token(binding)
        if mode != "subscribe" or not challenge or not hmac.compare_digest(supplied, expected):
            raise ChannelAuthorizationError("WhatsApp verification token is invalid")
        return PlainTextResponse(challenge)

    @app.post("/hooks/whatsapp/{binding_id}")
    async def ingest_whatsapp(binding_id: str, request: Request) -> dict[str, Any]:
        binding = active_channels.require_binding(binding_id, kind="whatsapp")
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
        binding = active_channels.require_binding(binding_id, kind="email")
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
        binding = active_channels.require_binding(binding_id, kind="webhook")
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
        except Exception as exc:
            _logger.exception("Kiro Bot WebSocket stream failed", exc_info=exc)
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "stream_failed",
                    "detail": "The live stream could not be completed",
                }
            )
            await websocket.close(code=1011)

    @app.websocket("/ws/live")
    async def stream_live(websocket: WebSocket) -> None:
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
    _validate_bot_name(name)
    bot = store.get_bot(name)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"bot {name!r} was not found")
    return bot


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
