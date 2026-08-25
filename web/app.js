const state = {
  bots: [],
  bot: null,
  run: null,
  socket: null,
  retryTimer: null,
  pollTimer: null,
  lastEvent: 0,
  messages: new Map(),
  permissions: new Map(),
  routines: [],
  plugins: [],
  bindings: [],
  delegations: [],
  codingExecutions: [],
  channels: [],
  channelEvents: [],
  memoryEvents: [],
};

const $ = (selector) => document.querySelector(selector);
const elements = {
  botList: $("#bot-list"), botCount: $("#bot-count"), title: $("#bot-title"), conversation: $("#conversation"),
  welcome: $("#welcome-state"), composer: $("#composer"), input: $("#message"), hint: $("#composer-hint"),
  send: $("#send-button"), stop: $("#stop-button"), runStatus: $("#run-status"), runCardState: $("#run-card-state"),
  runCardDetail: $("#run-card-detail"), pulse: $(".pulse"), eventList: $("#event-list"), activityEmpty: $("#activity-empty"),
  permissionSection: $("#permission-section"), permissionList: $("#permission-list"), dot: $("#connection-dot"), connection: $("#connection-label"),
  activity: $("#activity-panel"), dialog: $("#create-dialog"), createForm: $("#create-bot-form"), createError: $("#create-error"),
  toast: $("#toast-region"), mobileMenu: $("#mobile-menu"), rail: $(".bot-rail"),
  toggleActivity: $("#toggle-activity"),
  routineList: $("#routine-list"), pluginList: $("#plugin-list"), auditList: $("#audit-list"),
  policyForm: $("#policy-form"), routineDialog: $("#routine-dialog"), routineForm: $("#routine-form"),
  routineError: $("#routine-error"), pluginDialog: $("#plugin-dialog"), pluginForm: $("#plugin-form"),
  pluginError: $("#plugin-error"),
  delegationList: $("#delegation-list"), delegationDialog: $("#delegation-dialog"),
  delegationForm: $("#delegation-form"), delegationError: $("#delegation-error"),
  codingList: $("#coding-list"), codingDialog: $("#coding-dialog"),
  codingForm: $("#coding-form"), codingError: $("#coding-error"),
  channelList: $("#channel-list"), channelEventList: $("#channel-event-list"),
  channelDialog: $("#channel-dialog"), channelForm: $("#channel-form"), channelError: $("#channel-error"),
  memoryList: $("#memory-list"),
};

function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return fetch(path, { ...options, headers }).then(async (response) => {
    const body = await response.text();
    let data = {};
    try { data = body ? JSON.parse(body) : {}; } catch { data = { detail: body }; }
    if (!response.ok) throw new Error(data.detail || data.message || data.error || `Request failed (${response.status})`);
    return data;
  });
}

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function normalizeBots(data) {
  const bots = Array.isArray(data) ? data : (data.bots || data.items || []);
  return bots.filter(Boolean).map((bot) => typeof bot === "string" ? { name: bot } : bot);
}

function botName(bot) { return bot?.name || bot?.id || ""; }
function botMeta(bot) { return bot?.model || bot?.agent || bot?.cwd || "Persistent Kiro agent"; }
function setConnection(kind, label) { elements.dot.className = `connection-dot ${kind}`; elements.connection.textContent = label; }

function setRunState(kind, title, detail) {
  elements.runStatus.dataset.state = kind;
  elements.runStatus.textContent = title;
  elements.runCardState.textContent = title === "Idle" ? "No run in progress" : title;
  elements.runCardDetail.textContent = detail || "Tool activity and approval requests will appear here.";
  elements.pulse.classList.toggle("running", kind === "running");
  elements.stop.disabled = kind !== "running" && kind !== "waiting";
  elements.send.disabled = !state.bot || kind === "running" || kind === "waiting";
  elements.input.disabled = !state.bot;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

function toast(message, isError = false) {
  const notice = make("div", `toast${isError ? " error" : ""}`, message);
  elements.toast.append(notice);
  window.setTimeout(() => notice.remove(), 4400);
}

function renderBots() {
  clear(elements.botList);
  elements.botCount.textContent = state.bots.length ? String(state.bots.length).padStart(2, "0") : "";
  if (!state.bots.length) {
    elements.botList.append(make("p", "bot-meta rail-empty", "No bots yet"));
    return;
  }
  state.bots.forEach((bot) => {
    const name = botName(bot);
    const button = make("button", "bot-item");
    button.type = "button";
    button.setAttribute("aria-current", state.bot && botName(state.bot) === name ? "page" : "false");
    const avatar = make("span", "bot-avatar", name.slice(0, 1).toUpperCase() || "K");
    const labels = make("span");
    labels.append(make("span", "bot-name", name));
    labels.append(make("span", "bot-meta", botMeta(bot)));
    button.append(avatar, labels);
    button.addEventListener("click", () => selectBot(bot));
    elements.botList.append(button);
  });
}

function conversationShell() {
  clear(elements.conversation);
  const inner = make("div", "conversation-inner");
  elements.conversation.append(inner);
  return inner;
}

function addTurn(label) {
  const parent = elements.conversation.querySelector(".conversation-inner") || conversationShell();
  const turn = make("article", "turn");
  turn.append(make("div", "turn-label", label));
  parent.append(turn);
  return turn;
}

function addMessage(text, role, target) {
  const message = make("div", `message ${role}`, text);
  (target || addTurn(role === "user" ? "YOU" : "KIRO BOT")).append(message);
  scrollToBottom();
  return message;
}

function addTimeline(kind, detail) {
  elements.activityEmpty.hidden = true;
  const item = make("li", kind, detail || kind.replaceAll("_", " "));
  item.prepend(make("time", "", new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
  elements.eventList.prepend(item);
}

function scrollToBottom() { window.requestAnimationFrame(() => { elements.conversation.scrollTop = elements.conversation.scrollHeight; }); }

function normalizeHistory(data) {
  if (Array.isArray(data)) return data;
  return data.turns || data.history || data.items || [];
}

function historyEvents(turn) { return turn.events || turn.activity || []; }
function eventText(event) { return event?.text || event?.content || event?.message || event?.title || ""; }

function renderHistory(data) {
  // The durable history API is chronological so no client-side reordering can
  // invert an already-bounded slice of recent turns.
  const turns = normalizeHistory(data);
  state.messages.clear(); state.permissions.clear(); clear(elements.eventList); elements.activityEmpty.hidden = true;
  const inner = conversationShell();
  if (!turns.length) {
    const empty = make("div", "history-empty");
    empty.append(make("p", "eyebrow", "READY WHEN YOU ARE"));
    empty.append(make("h2", "", "Start the first run."));
    empty.append(make("p", "", "Ask this bot to inspect a workspace, plan a task, or take action with your approval."));
    inner.append(empty);
    return;
  }
  for (const turn of turns) {
    const prompt = turn.prompt || turn.message || turn.input || "";
    if (prompt) addMessage(prompt, "user", addTurn("YOU"));
    const assistantTurn = addTurn("KIRO BOT");
    const answer = make("div", "message assistant");
    let sawText = false;
    for (const storedEvent of historyEvents(turn)) {
      // Durable history wraps the original event in { sequence, kind, payload }.
      const event = storedEvent?.payload && typeof storedEvent.payload === "object" ? storedEvent.payload : storedEvent;
      const kind = event.kind || storedEvent.kind || event.type || "event";
      const text = eventText(event);
      if (kind === "text" || kind === "agent_message_chunk" || kind === "assistant") { answer.textContent += text; sawText = true; }
      else if (kind === "thinking" && text) assistantTurn.append(make("div", "message thinking", text));
      else if (kind.includes("tool")) addTimeline("tool", event.title || text || "Tool activity");
    }
    if (sawText) assistantTurn.append(answer);
  }
  if (!elements.eventList.children.length) elements.activityEmpty.hidden = false;
  scrollToBottom();
}

async function loadBots() {
  try {
    const data = await request("/api/bots");
    state.bots = normalizeBots(data);
    renderBots(); setConnection("online", "Control plane online");
    const requested = new URLSearchParams(location.search).get("bot");
    const preferred = state.bots.find((b) => botName(b) === requested) || state.bots.find((b) => state.bot && botName(b) === botName(state.bot));
    if (preferred && (!state.bot || botName(preferred) !== botName(state.bot))) await selectBot(preferred, false);
  } catch (error) {
    setConnection("offline", "Control plane unavailable");
    toast(error.message || "Could not load bots", true);
  }
}

async function selectBot(bot, shouldPush = true) {
  closeRun(); state.bot = bot; renderBots(); elements.title.textContent = botName(bot); elements.input.disabled = false;
  elements.hint.textContent = `Persistent session · ${botMeta(bot)}`;
  setRunState("idle", "Idle");
  if (shouldPush) { const url = new URL(location.href); url.searchParams.set("bot", botName(bot)); history.replaceState({}, "", url); }
  clear(elements.eventList); elements.activityEmpty.hidden = false; clear(elements.permissionList); elements.permissionSection.hidden = true;
  const inner = conversationShell(); inner.append(make("div", "history-empty", "Loading conversation…"));
  try {
    const data = await request(`/api/bots/${encodeURIComponent(botName(bot))}/history`);
    renderHistory(data);
  } catch (error) { renderHistory([]); const node = make("div", "error-state"); node.append(make("h2", "", "Couldn’t load this conversation")); node.append(make("p", "", error.message)); const retry = make("button", "retry-button", "Try again"); retry.addEventListener("click", () => selectBot(bot, false)); node.append(retry); elements.conversation.querySelector(".conversation-inner").append(node); }
  loadManagement();
}

function csv(value) { return String(value || "").split(",").map((item) => item.trim()).filter(Boolean); }

function managementCard(title, meta, badge, enabled = true) {
  const card = make("article", "management-card");
  const top = make("div", "management-card-top");
  top.append(make("div", "management-title", title), make("span", `management-badge${enabled ? "" : " off"}`, badge));
  card.append(top, make("div", "management-meta", meta));
  return card;
}

function renderRoutines() {
  clear(elements.routineList);
  if (!state.routines.length) { elements.routineList.append(make("p", "activity-empty", "No routines yet.")); return; }
  state.routines.forEach((routine) => {
    const schedule = routine.trigger_kind === "once" ? `Once · ${new Date(routine.run_at).toLocaleString()}` : `Every ${Math.round(routine.interval_seconds / 60)} min`;
    const card = managementCard(routine.name, `${schedule}\nNext: ${routine.next_run_at ? new Date(routine.next_run_at).toLocaleString() : "not scheduled"}`, routine.enabled ? "active" : "paused", routine.enabled);
    const toggle = make("button", "danger-link", routine.enabled ? "Pause" : "Resume");
    toggle.addEventListener("click", async () => { try { await request(`/api/routines/${encodeURIComponent(routine.id)}`, { method:"PATCH", body:JSON.stringify({ enabled: !routine.enabled }) }); await loadManagement(); } catch (error) { toast(error.message, true); } });
    const remove = make("button", "danger-link", "Delete"); remove.style.marginLeft = "12px";
    remove.addEventListener("click", async () => { try { await request(`/api/routines/${encodeURIComponent(routine.id)}`, { method:"DELETE" }); await loadManagement(); } catch (error) { toast(error.message, true); } });
    card.append(toggle, remove); elements.routineList.append(card);
  });
}

function renderPolicy(policy) {
  $("#approval-mode").value = policy.approval_mode || "ask";
  $("#allowed-tools").value = (policy.allowed_tools || []).join(", ");
  $("#denied-tools").value = (policy.denied_tools || []).join(", ");
  $("#quota-hour").value = policy.max_turns_per_hour || 0;
  $("#quota-concurrent").value = policy.max_concurrent_runs || 0;
  $("#quota-day").value = policy.max_daily_runs || 0;
}

function renderPlugins() {
  clear(elements.pluginList);
  if (!state.bindings.length) { elements.pluginList.append(make("p", "activity-empty", "No MCP connections for this bot.")); return; }
  state.bindings.forEach((binding) => {
    const plugin = state.plugins.find((item) => item.id === binding.plugin_id) || {};
    const tools = binding.allow_tools?.includes("*") ? "All tools" : `${(binding.allow_tools || []).length} allowed tool(s)`;
    const card = managementCard(plugin.name || binding.plugin_id, `${plugin.transport || "MCP"} · ${tools}`, binding.enabled ? "connected" : "off", binding.enabled);
    const remove = make("button", "danger-link", "Disconnect");
    remove.addEventListener("click", async () => { try { await request(`/api/bots/${encodeURIComponent(botName(state.bot))}/plugins/${encodeURIComponent(binding.plugin_id)}`, { method:"DELETE" }); await loadManagement(); } catch (error) { toast(error.message, true); } });
    card.append(remove); elements.pluginList.append(card);
  });
}

function renderDelegations() {
  clear(elements.delegationList);
  if (!state.delegations.length) { elements.delegationList.append(make("p", "activity-empty", "No team plans yet.")); return; }
  [...state.delegations].reverse().forEach((plan) => {
    const terminal = ["succeeded", "failed", "cancelled"].includes(plan.status);
    const card = managementCard(plan.name, `Up to ${plan.max_fanout} bots in parallel · depth ${plan.max_depth}`, plan.status, !terminal || plan.status === "succeeded");
    if (plan.status === "paused") {
      const start = make("button", "danger-link", "Start plan");
      start.addEventListener("click", async () => { try { await request(`/api/delegations/${encodeURIComponent(plan.id)}/start`, { method:"POST" }); await refreshDelegations(); } catch (error) { toast(error.message, true); } });
      card.append(start);
    }
    if (!terminal) {
      const cancel = make("button", "danger-link", "Cancel plan");
      if (plan.status === "paused") cancel.style.marginLeft = "12px";
      cancel.addEventListener("click", async () => { try { await request(`/api/delegations/${encodeURIComponent(plan.id)}/cancel`, { method:"POST" }); await loadManagement(); } catch (error) { toast(error.message, true); } });
      card.append(cancel);
    }
    elements.delegationList.append(card);
  });
}

function renderCodingExecutions() {
  clear(elements.codingList);
  if (!state.codingExecutions.length) { elements.codingList.append(make("p", "activity-empty", "No coding executions yet.")); return; }
  state.codingExecutions.forEach((execution) => {
    const spec = execution.spec || {};
    const task = String(spec.task || "Coding execution");
    const repairs = execution.result?.repair_attempts_used ?? 0;
    const card = managementCard(
      task.length > 64 ? `${task.slice(0, 61)}…` : task,
      `${spec.builder_bot || "builder"} → ${spec.reviewer_bot || "reviewer"} · ${repairs} repair(s)`,
      String(execution.status || "queued").replaceAll("_", " "),
      !["failed", "cancelled"].includes(execution.status),
    );
    if (execution.status === "awaiting_handoff") {
      const approve = make("button", "danger-link", "Approve handoff");
      approve.addEventListener("click", async () => { try { await request(`/api/coding-executions/${encodeURIComponent(execution.id)}/approve`, { method:"POST", body:JSON.stringify({ expected_version:execution.version }) }); toast("Verified handoff approved."); await refreshCodingExecutions(); } catch (error) { toast(error.message, true); } });
      card.append(approve);
    }
    if (!["ready", "failed", "cancelled"].includes(execution.status)) {
      const cancel = make("button", "danger-link", "Cancel"); cancel.style.marginLeft = "12px";
      cancel.addEventListener("click", async () => { try { await request(`/api/coding-executions/${encodeURIComponent(execution.id)}/cancel`, { method:"POST" }); await refreshCodingExecutions(); } catch (error) { toast(error.message, true); } });
      card.append(cancel);
    }
    elements.codingList.append(card);
  });
}

function renderChannels() {
  clear(elements.channelList);
  if (!state.channels.length) { elements.channelList.append(make("p", "activity-empty", "No remote channels yet.")); }
  state.channels.forEach((channel) => {
    const hookKind = channel.kind === "webhook" ? "webhook" : channel.kind;
    const hookPath = `/hooks/${hookKind}/${encodeURIComponent(channel.id)}`;
    const delivery = channel.outbound_delivery_configured ? "Replies enabled" : "Replies stored here";
    const card = managementCard(channel.name, `${channel.kind.toUpperCase()} · ${delivery}\n${hookPath}`, channel.enabled ? "active" : "paused", channel.enabled);
    const copy = make("button", "danger-link", "Copy webhook URL");
    copy.addEventListener("click", async () => { try { await navigator.clipboard.writeText(`${location.origin}${hookPath}`); toast("Webhook URL copied."); } catch { toast("Could not copy the URL.", true); } });
    const toggle = make("button", "danger-link", channel.enabled ? "Pause" : "Resume"); toggle.style.marginLeft = "12px";
    toggle.addEventListener("click", async () => { try { await request(`/api/channels/${encodeURIComponent(channel.id)}`, { method:"PATCH", body:JSON.stringify({ enabled:!channel.enabled }) }); await loadManagement(); } catch (error) { toast(error.message, true); } });
    const remove = make("button", "danger-link", "Delete"); remove.style.marginLeft = "12px";
    remove.addEventListener("click", async () => { try { await request(`/api/channels/${encodeURIComponent(channel.id)}`, { method:"DELETE" }); await loadManagement(); } catch (error) { toast(error.message, true); } });
    card.append(copy, toggle, remove); elements.channelList.append(card);
  });

  clear(elements.channelEventList);
  const bindingIds = new Set(state.channels.map((channel) => channel.id));
  const events = state.channelEvents.filter((event) => bindingIds.has(event.binding_id)).slice(0, 12);
  if (!events.length) { elements.channelEventList.append(make("p", "activity-empty", "No remote requests yet.")); return; }
  events.forEach((event) => {
    const requestText = String(event.text || "Remote request").replaceAll("\n", " ");
    const title = requestText.length > 58 ? `${requestText.slice(0, 55)}…` : requestText;
    const meta = `${event.sender} · ${event.source}\n${event.response_text ? `Reply: ${String(event.response_text).slice(0, 90)}` : (event.error || "Processing")}`;
    elements.channelEventList.append(managementCard(title, meta, event.status, !["failed", "cancelled"].includes(event.status)));
  });
}

function renderMemory() {
  clear(elements.memoryList);
  if (!state.memoryEvents.length) {
    elements.memoryList.append(make("p", "activity-empty", "No shared memories yet."));
    return;
  }
  state.memoryEvents.slice(0, 30).forEach((event) => {
    const requestText = String(event.request_text || "Recorded exchange").replaceAll("\n", " ");
    const title = requestText.length > 62 ? `${requestText.slice(0, 59)}…` : requestText;
    const responseText = String(event.response_text || "No textual response").replaceAll("\n", " ");
    const timestamp = event.created_at ? new Date(event.created_at).toLocaleString([], { dateStyle:"short", timeStyle:"short" }) : "";
    const source = String(event.scope || "unknown").replace(/^channel:/, "");
    elements.memoryList.append(managementCard(
      title,
      `${responseText.slice(0, 150)}${responseText.length > 150 ? "…" : ""}\n${timestamp}`,
      source,
      true,
    ));
  });
}

async function refreshCodingExecutions() {
  try {
    state.codingExecutions = await request("/api/coding-executions");
    renderCodingExecutions();
  } catch (error) {
    console.warn("Could not refresh coding executions", error);
  }
}

async function refreshDelegations() {
  try {
    state.delegations = await request("/api/delegations");
    renderDelegations();
  } catch (error) {
    console.warn("Could not refresh team plans", error);
  }
}

function renderAudit(items) {
  clear(elements.auditList);
  if (!items.length) { elements.auditList.append(make("p", "activity-empty", "No decisions recorded.")); return; }
  items.slice(0, 8).forEach((item) => {
    const label = item.event_type.replaceAll("_", " ");
    const detail = `${item.outcome} · ${item.reason}${item.canonical_tool_name ? ` · ${item.canonical_tool_name}` : ""}`;
    elements.auditList.append(managementCard(label, detail, new Date(item.created_at).toLocaleTimeString([], { hour:"2-digit", minute:"2-digit" })));
  });
}

async function loadManagement() {
  if (!state.bot) return;
  const name = encodeURIComponent(botName(state.bot));
  try {
    const [policy, routines, plugins, bindings, audit, delegations, codingExecutions, channels, channelEvents, memory] = await Promise.all([
      request(`/api/bots/${name}/policy`), request(`/api/routines?bot_name=${name}`), request("/api/plugins"),
      request(`/api/bots/${name}/plugins`), request(`/api/audit?bot_name=${name}&limit=8`), request("/api/delegations"), request("/api/coding-executions"),
      request(`/api/channels?bot_name=${name}`), request("/api/channel-events?limit=50"), request(`/api/bots/${name}/memory?limit=50`),
    ]);
    state.routines = routines; state.plugins = plugins; state.bindings = bindings; state.delegations = delegations; state.codingExecutions = codingExecutions; state.channels = channels; state.channelEvents = channelEvents; state.memoryEvents = memory.events || [];
    renderPolicy(policy); renderRoutines(); renderPlugins(); renderAudit(audit); renderDelegations(); renderCodingExecutions(); renderChannels(); renderMemory();
  } catch (error) { toast(error.message || "Could not load bot controls", true); }
}

function eventId(event) { return Number(event?.id || event?.sequence || event?.offset || 0); }
function parseEvent(payload) {
  if (typeof payload === "string") { try { return JSON.parse(payload); } catch { return { kind: "text", text: payload }; } }
  return payload || {};
}

function receiveEvent(payload) {
  const envelope = parseEvent(payload);
  if (envelope.type === "terminal") {
    const status = envelope.run?.status || "complete";
    if (status === "failed") finishRun("Error", envelope.run?.error || "Run failed");
    else finishRun("Idle", envelope.run?.stop_reason || (status === "cancelled" ? "Run cancelled" : "Run complete"));
    return;
  }
  if (envelope.type === "error" && !envelope.kind) {
    finishRun("Error", envelope.detail || "Live stream failed");
    toast(envelope.detail || "Live stream failed", true);
    return;
  }
  const event = envelope.event || envelope.data || envelope;
  const id = eventId(envelope) || eventId(event);
  if (id > state.lastEvent) state.lastEvent = id;
  const kind = event.kind || event.type || "event";
  const text = eventText(event);
  if (kind === "text" || kind === "agent_message_chunk" || kind === "assistant") {
    let node = state.messages.get("assistant");
    if (!node) { const turn = addTurn("KIRO BOT"); node = addMessage("", "assistant", turn); node.append(make("span", "streaming-cursor")); state.messages.set("assistant", node); }
    const cursor = node.querySelector(".streaming-cursor");
    if (cursor) node.removeChild(cursor);
    node.append(document.createTextNode(text));
    node.append(make("span", "streaming-cursor")); scrollToBottom();
  } else if (kind === "thinking" || kind === "agent_thought_chunk") {
    if (text) addMessage(text, "thinking", state.messages.get("assistant")?.parentElement || addTurn("REASONING"));
  } else if (kind === "permission") {
    setRunState("waiting", "Approval needed", event.title || "Kiro needs permission to continue.");
    showPermission(event);
    addTimeline("permission", event.title || "Permission requested");
  } else if (kind.includes("tool")) {
    const title = event.title || text || "Tool activity";
    addTimeline("tool", title);
    if (state.run) setRunState("running", "Working", title);
  } else if (kind === "complete" || kind === "done") {
    finishRun("Idle", event.stop_reason || "Run complete"); addTimeline("complete", "Run completed");
  } else if (kind === "error" || kind === "failed") {
    finishRun("Error", text || "The run failed"); addTimeline("error", text || "Run failed"); toast(text || "Run failed", true);
  }
}

function showPermission(event) {
  const id = String(event.request_id || event.requestId || event.id || crypto.randomUUID());
  if (state.permissions.has(id)) return;
  state.permissions.set(id, event); elements.permissionSection.hidden = false;
  const card = make("article", "permission-card"); card.dataset.permissionId = id;
  card.append(make("div", "permission-title", event.title || "Tool permission requested"));
  const buttons = make("div", "permission-buttons");
  const allow = make("button", "approve", "Allow once"); allow.type = "button"; allow.addEventListener("click", () => decidePermission(id, "allow_once"));
  const reject = make("button", "", "Reject"); reject.type = "button"; reject.addEventListener("click", () => decidePermission(id, "reject"));
  buttons.append(allow, reject); card.append(buttons); elements.permissionList.append(card);
}

async function decidePermission(id, decision) {
  if (!state.run) return;
  const body = { decision: decision === "allow_once" ? "once" : decision };
  try {
    await request(`/api/runs/${encodeURIComponent(state.run.id)}/permissions/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify(body) });
    state.permissions.delete(id); elements.permissionList.querySelector(`[data-permission-id="${CSS.escape(id)}"]`)?.remove();
    elements.permissionSection.hidden = !elements.permissionList.children.length;
    setRunState("running", "Working", "Approval recorded. Continuing the run.");
  } catch (error) { toast(error.message || "Could not submit decision", true); }
}

function closeRun() {
  if (state.socket) { state.socket.onclose = null; state.socket.close(); state.socket = null; }
  if (state.retryTimer) { clearTimeout(state.retryTimer); state.retryTimer = null; }
  if (state.pollTimer) { clearTimeout(state.pollTimer); state.pollTimer = null; }
  state.run = null; state.lastEvent = 0; state.messages.clear(); state.permissions.clear();
}

function finishRun(status = "Idle", detail = "") {
  const active = state.messages.get("assistant"); active?.querySelector(".streaming-cursor")?.remove(); state.messages.clear();
  if (status === "Error") setRunState("error", status, detail); else setRunState("idle", status, detail);
  if (state.socket) { state.socket.onclose = null; state.socket.close(); state.socket = null; }
  if (state.pollTimer) { clearTimeout(state.pollTimer); state.pollTimer = null; }
  state.run = null;
}

function connectRun() {
  if (!state.run) return;
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${location.host}/ws/runs/${encodeURIComponent(state.run.id)}?after=${state.lastEvent}`;
  try {
    const socket = new WebSocket(url); state.socket = socket;
    socket.onopen = () => { setConnection("online", "Live stream connected"); };
    socket.onmessage = (message) => receiveEvent(message.data);
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      if (!state.run || state.socket !== socket) return;
      setConnection("online", "Reconnecting stream");
      pollRun();
      state.retryTimer = setTimeout(connectRun, 1500);
    };
  } catch { pollRun(); }
}

async function pollRun() {
  if (!state.run) return;
  try {
    const data = await request(`/api/runs/${encodeURIComponent(state.run.id)}?after=${state.lastEvent}`);
    const events = Array.isArray(data) ? data : (data.events || data.items || []);
    events.forEach(receiveEvent);
    const status = data.status || data.state;
    if (status && ["complete", "completed", "cancelled", "failed", "error"].includes(String(status).toLowerCase())) {
      if (status === "failed" || status === "error") finishRun("Error", data.detail || "Run failed"); else finishRun("Idle", data.detail || "Run complete");
      return;
    }
  } catch { setConnection("offline", "Reconnecting control plane"); }
  if (state.run) state.pollTimer = setTimeout(pollRun, 1800);
}

async function submitTurn(event) {
  event.preventDefault();
  const message = elements.input.value.trim(); if (!message || !state.bot || state.run) return;
  const priorEmpty = elements.conversation.querySelector(".history-empty"); priorEmpty?.remove();
  addMessage(message, "user", addTurn("YOU")); elements.input.value = ""; resizeInput(); setRunState("running", "Starting", "Creating a persistent Kiro run…");
  try {
    const data = await request(`/api/bots/${encodeURIComponent(botName(state.bot))}/turns`, { method:"POST", body:JSON.stringify({ message }) });
    const id = data.run_id || data.id || data.run?.id;
    if (!id) throw new Error("The server did not return a run ID.");
    state.run = { id: String(id) }; state.lastEvent = 0; state.messages.clear(); setRunState("running", "Working", "Kiro is working in this bot’s persistent session."); connectRun(); pollRun();
  } catch (error) { finishRun("Error", error.message); toast(error.message || "Could not start run", true); }
}

async function cancelRun() {
  if (!state.run) return;
  const id = state.run.id; elements.stop.disabled = true;
  try { await request(`/api/runs/${encodeURIComponent(id)}/cancel`, { method:"POST" }); setRunState("running", "Stopping", "Requesting a clean stop…"); }
  catch (error) { toast(error.message || "Could not cancel run", true); elements.stop.disabled = false; }
}

function resizeInput() { elements.input.style.height = "auto"; elements.input.style.height = `${Math.min(elements.input.scrollHeight, 170)}px`; }

async function createBot(event) {
  event.preventDefault(); elements.createError.textContent = "";
  const form = new FormData(elements.createForm);
  const payload = Object.fromEntries([...form.entries()].map(([key, value]) => [key, String(value).trim()]));
  try {
    const response = await request("/api/bots", { method:"POST", body:JSON.stringify(payload) });
    const bot = response.bot || response; state.bots = state.bots.filter((item) => botName(item) !== botName(bot)); state.bots.push(bot); elements.dialog.close(); elements.createForm.reset(); renderBots(); await selectBot(bot); toast(`${botName(bot)} is ready.`);
  } catch (error) { elements.createError.textContent = error.message || "Could not create bot"; }
}

async function savePolicy(event) {
  event.preventDefault(); if (!state.bot) return;
  const payload = {
    approval_mode: $("#approval-mode").value,
    allowed_tools: csv($("#allowed-tools").value),
    denied_tools: csv($("#denied-tools").value),
    max_turns_per_hour: Number($("#quota-hour").value || 0),
    max_concurrent_runs: Number($("#quota-concurrent").value || 0),
    max_daily_runs: Number($("#quota-day").value || 0),
  };
  try { await request(`/api/bots/${encodeURIComponent(botName(state.bot))}/policy`, { method:"PUT", body:JSON.stringify(payload) }); toast("Safety policy saved."); await loadManagement(); }
  catch (error) { toast(error.message || "Could not save policy", true); }
}

async function createRoutine(event) {
  event.preventDefault(); if (!state.bot) return; elements.routineError.textContent = "";
  const form = new FormData(elements.routineForm); const kind = String(form.get("trigger_kind"));
  const payload = { name:String(form.get("name") || "").trim(), bot_name:botName(state.bot), prompt:String(form.get("prompt") || "").trim(), trigger_kind:kind };
  if (kind === "interval") payload.interval_seconds = Number(form.get("interval_minutes") || 0) * 60;
  else { const raw = String(form.get("run_at") || ""); payload.run_at = raw ? new Date(raw).toISOString() : ""; }
  try { await request("/api/routines", { method:"POST", body:JSON.stringify(payload) }); elements.routineDialog.close(); elements.routineForm.reset(); toast("Routine scheduled."); await loadManagement(); }
  catch (error) { elements.routineError.textContent = error.message || "Could not create routine"; }
}

function parseEnvReferences(raw) {
  const result = {};
  String(raw || "").split(/\n|,/).map((line) => line.trim()).filter(Boolean).forEach((line) => {
    const split = line.indexOf("="); if (split < 1) throw new Error("Environment references must use NAME=env:SOURCE.");
    result[line.slice(0, split).trim()] = line.slice(split + 1).trim();
  });
  return result;
}

async function createPlugin(event) {
  event.preventDefault(); if (!state.bot) return; elements.pluginError.textContent = "";
  try {
    const form = new FormData(elements.pluginForm); const transport = String(form.get("transport"));
    const payload = { id:String(form.get("id") || "").trim(), name:String(form.get("name") || "").trim(), transport, command:"", args:[], url:"", env:{} };
    if (transport === "stdio") { payload.command = String(form.get("command") || "").trim(); payload.args = csv(form.get("args")); payload.env = parseEnvReferences(form.get("env")); }
    else payload.url = String(form.get("url") || "").trim();
    await request("/api/plugins", { method:"POST", body:JSON.stringify(payload) });
    await request(`/api/bots/${encodeURIComponent(botName(state.bot))}/plugins/${encodeURIComponent(payload.id)}`, { method:"PUT", body:JSON.stringify({ allow_tools:["*"] }) });
    elements.pluginDialog.close(); elements.pluginForm.reset(); toast("Connection added."); await loadManagement();
  } catch (error) { elements.pluginError.textContent = error.message || "Could not add connection"; }
}

async function createDelegation(event) {
  event.preventDefault(); elements.delegationError.textContent = "";
  const form = new FormData(elements.delegationForm);
  try {
    const tasks = String(form.get("tasks") || "").split("\n").map((line) => line.trim()).filter(Boolean).map((line, index) => {
      const split = line.indexOf(":");
      if (split < 1 || !line.slice(split + 1).trim()) throw new Error(`Line ${index + 1} must use bot-name: instruction.`);
      const instruction = line.slice(split + 1).trim();
      const dependencySplit = instruction.lastIndexOf(" <- ");
      const prompt = dependencySplit < 0 ? instruction : instruction.slice(0, dependencySplit).trim();
      const after = dependencySplit < 0 ? [] : csv(instruction.slice(dependencySplit + 4)).map((value) => Number(value));
      if (!prompt || after.some((value) => !Number.isInteger(value) || value < 1)) throw new Error(`Line ${index + 1} has invalid dependencies.`);
      return { id:`task-${index + 1}`, bot_name:line.slice(0, split).trim(), prompt, after };
    });
    if (!tasks.length) throw new Error("Add at least one bot task.");
    const edges = tasks.flatMap((task) => task.after.map((dependency) => ({ source:`task-${dependency}`, target:task.id })));
    const nodes = tasks.map(({ after, ...task }) => task);
    await request("/api/delegations", { method:"POST", body:JSON.stringify({ name:String(form.get("name") || "").trim(), nodes, edges }) });
    elements.delegationDialog.close(); elements.delegationForm.reset(); toast("Team plan started."); await loadManagement();
  } catch (error) { elements.delegationError.textContent = error.message || "Could not start team"; }
}

async function createCodingExecution(event) {
  event.preventDefault();
  if (!state.bot) return;
  elements.codingError.textContent = "";
  const form = new FormData(elements.codingForm);
  try {
    const checks = String(form.get("checks") || "").split("\n").map((line) => line.trim()).filter(Boolean).map((line, index) => {
      const split = line.indexOf(":");
      if (split < 1) throw new Error(`Check line ${index + 1} must use name: executable, argument.`);
      const argv = csv(line.slice(split + 1));
      if (!argv.length) throw new Error(`Check line ${index + 1} has no executable.`);
      return { name:line.slice(0, split).trim(), argv };
    });
    if (!checks.length) throw new Error("Add at least one deterministic check.");
    const payload = {
      idempotency_key:`browser-${crypto.randomUUID()}`,
      repo_path:String(form.get("repo_path") || "").trim(),
      task:String(form.get("task") || "").trim(),
      builder_bot:botName(state.bot),
      reviewer_bot:String(form.get("reviewer_bot") || "").trim(),
      checks,
      max_repairs:Number(form.get("max_repairs") || 0),
    };
    await request("/api/coding-executions", { method:"POST", body:JSON.stringify(payload) });
    elements.codingDialog.close(); elements.codingForm.reset();
    toast("Isolated coding execution started.");
    await refreshCodingExecutions();
  } catch (error) { elements.codingError.textContent = error.message || "Could not start coding execution"; }
}

async function createChannel(event) {
  event.preventDefault();
  if (!state.bot) return;
  elements.channelError.textContent = "";
  const form = new FormData(elements.channelForm);
  const payload = {
    id:String(form.get("id") || "").trim(),
    name:String(form.get("name") || "").trim(),
    kind:String(form.get("kind") || "").trim(),
    bot_name:botName(state.bot),
    signing_secret_env:String(form.get("signing_secret_env") || "").trim(),
    verify_token_env:String(form.get("verify_token_env") || "").trim(),
    outbound_token_env:String(form.get("outbound_token_env") || "").trim(),
    trigger_prefix:String(form.get("trigger_prefix") || "").trim(),
    allowed_sources:csv(form.get("allowed_sources")),
    allowed_senders:csv(form.get("allowed_senders")),
  };
  try {
    await request("/api/channels", { method:"POST", body:JSON.stringify(payload) });
    elements.channelDialog.close(); elements.channelForm.reset();
    elements.channelForm.querySelector('[name="trigger_prefix"]').value = "@kiro";
    toast("Remote channel created."); await loadManagement();
  } catch (error) { elements.channelError.textContent = error.message || "Could not create channel"; }
}

function switchPanel(name) {
  document.querySelectorAll(".panel-tabs button").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.panel === name)));
  document.querySelectorAll(".panel-view").forEach((view) => { view.hidden = view.dataset.view !== name; });
  if (name !== "run") loadManagement();
}

elements.composer.addEventListener("submit", submitTurn);
elements.stop.addEventListener("click", cancelRun);
elements.input.addEventListener("input", resizeInput);
elements.input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); elements.composer.requestSubmit(); } });
$("#new-bot-button").addEventListener("click", () => elements.dialog.showModal());
$("#cancel-create").addEventListener("click", () => elements.dialog.close());
elements.createForm.addEventListener("submit", createBot);
elements.policyForm.addEventListener("submit", savePolicy);
elements.routineForm.addEventListener("submit", createRoutine);
elements.pluginForm.addEventListener("submit", createPlugin);
elements.delegationForm.addEventListener("submit", createDelegation);
elements.codingForm.addEventListener("submit", createCodingExecution);
elements.channelForm.addEventListener("submit", createChannel);
document.querySelectorAll(".panel-tabs button").forEach((button) => button.addEventListener("click", () => switchPanel(button.dataset.panel)));
$("#new-routine-button").addEventListener("click", () => { if (!state.bot) return toast("Choose a bot first.", true); elements.routineDialog.showModal(); });
$("#new-plugin-button").addEventListener("click", () => { if (!state.bot) return toast("Choose a bot first.", true); elements.pluginDialog.showModal(); });
$("#new-delegation-button").addEventListener("click", () => elements.delegationDialog.showModal());
$("#new-coding-button").addEventListener("click", () => {
  if (!state.bot) return toast("Choose the builder bot first.", true);
  elements.codingForm.querySelector('[name="repo_path"]').value = state.bot.cwd || "";
  elements.codingDialog.showModal();
});
$("#new-channel-button").addEventListener("click", () => { if (!state.bot) return toast("Choose a bot first.", true); elements.channelDialog.showModal(); });
$("#routine-kind").addEventListener("change", (event) => { const once = event.target.value === "once"; $("#interval-field").hidden = once; $("#once-field").hidden = !once; });
elements.delegationForm.querySelector('[name="tasks"]').placeholder = "researcher: Investigate the design\nbuilder: Implement the fix <- 1\nreviewer: Review the result <- 2";
setInterval(() => {
  const teams = document.querySelector('.panel-view[data-view="teams"]');
  if (teams && !teams.hidden) refreshDelegations();
}, 2000);
setInterval(() => {
  const coding = document.querySelector('.panel-view[data-view="coding"]');
  if (coding && !coding.hidden) refreshCodingExecutions();
}, 2000);
$("#plugin-transport").addEventListener("change", (event) => { const http = event.target.value === "http"; $("#stdio-fields").hidden = http; $("#http-field").hidden = !http; });
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => document.getElementById(button.dataset.close).close()));
elements.toggleActivity.addEventListener("click", () => {
  const hidden = elements.activity.classList.toggle("is-hidden");
  elements.toggleActivity.setAttribute("aria-expanded", String(!hidden));
});
$("#close-activity").addEventListener("click", () => {
  elements.activity.classList.add("is-hidden");
  elements.toggleActivity.setAttribute("aria-expanded", "false");
});
elements.mobileMenu.addEventListener("click", () => elements.rail.classList.toggle("is-open"));
window.addEventListener("popstate", () => { const name = new URLSearchParams(location.search).get("bot"); const bot = state.bots.find((item) => botName(item) === name); if (bot) selectBot(bot, false); });

// On tablet/mobile the activity panel is a drawer. Start it closed so the
// conversation and composer are usable immediately instead of being covered.
if (window.matchMedia("(max-width: 1080px)").matches) {
  elements.activity.classList.add("is-hidden");
  elements.toggleActivity.setAttribute("aria-expanded", "false");
}

setRunState("idle", "Idle");
loadBots();
