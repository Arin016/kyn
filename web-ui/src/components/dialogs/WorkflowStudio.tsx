import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import api from "../../api";
import type { Bot, DelegationDetail } from "../../types";

const BOARD_WIDTH = 2200;
const BOARD_HEIGHT = 1400;
const NODE_WIDTH = 280;
const NODE_HEIGHT = 230;

interface CanvasNode {
  id: string;
  botName: string;
  prompt: string;
  after: string[];
  x: number;
  y: number;
  status?: string;
  result?: unknown;
  error?: string;
}

interface DragState {
  id: string;
  pointerX: number;
  pointerY: number;
  nodeX: number;
  nodeY: number;
}

interface Props {
  activePlan?: DelegationDetail | null;
  draftKey: number;
  onDone: () => void;
  bots: Bot[];
  onStartPlan?: (planId: string) => void;
  onCancelPlan?: (planId: string) => void;
}

function createNode(botName: string, x: number, y: number): CanvasNode {
  return {
    id: crypto.randomUUID(),
    botName,
    prompt: "",
    after: [],
    x,
    y,
  };
}

function seededNodes(bots: Bot[]): CanvasNode[] {
  const first = createNode(bots[0]?.name || "", 90, 150);
  const second = createNode(bots[1]?.name || bots[0]?.name || "", 520, 150);
  second.after = [first.id];
  return [first, second];
}

function nodesFromPlan(plan: DelegationDetail): CanvasNode[] {
  const incoming = new Map<string, string[]>();
  for (const edge of plan.edges) incoming.set(edge.target, [...(incoming.get(edge.target) || []), edge.source]);
  const raw = plan.nodes.map((node) => ({
    id: node.id,
    botName: node.bot_name,
    prompt: node.prompt,
    after: incoming.get(node.id) || [],
    x: 0,
    y: 0,
    status: node.status,
    result: node.result,
    error: node.error,
  }));
  return layoutNodes(raw);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function edgePath(source: CanvasNode, target: CanvasNode): string {
  const sx = source.x + NODE_WIDTH;
  const sy = source.y + 94;
  const tx = target.x;
  const ty = target.y + 94;
  const bend = Math.max(80, Math.abs(tx - sx) * 0.45);
  return `M ${sx} ${sy} C ${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`;
}

function introducesCycle(nodes: CanvasNode[], sourceId: string, targetId: string): boolean {
  if (sourceId === targetId) return true;
  const outgoing = new Map<string, string[]>();
  for (const node of nodes) {
    for (const parent of node.after) {
      outgoing.set(parent, [...(outgoing.get(parent) || []), node.id]);
    }
  }
  outgoing.set(sourceId, [...(outgoing.get(sourceId) || []), targetId]);
  const queue = [targetId];
  const seen = new Set<string>();
  while (queue.length) {
    const current = queue.shift()!;
    if (current === sourceId) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    queue.push(...(outgoing.get(current) || []));
  }
  return false;
}

function layoutNodes(nodes: CanvasNode[]): CanvasNode[] {
  const levels = new Map<string, number>();
  const remaining = new Set(nodes.map((node) => node.id));
  while (remaining.size) {
    let progressed = false;
    for (const node of nodes) {
      if (!remaining.has(node.id)) continue;
      if (node.after.every((id) => levels.has(id))) {
        levels.set(node.id, node.after.length ? Math.max(...node.after.map((id) => levels.get(id) || 0)) + 1 : 0);
        remaining.delete(node.id);
        progressed = true;
      }
    }
    if (!progressed) break;
  }
  const rowByLevel = new Map<number, number>();
  return nodes.map((node) => {
    const level = levels.get(node.id) || 0;
    const row = rowByLevel.get(level) || 0;
    rowByLevel.set(level, row + 1);
    return { ...node, x: 80 + level * 410, y: 110 + row * 280 };
  });
}

export function WorkflowStudio({ activePlan = null, draftKey, onDone, bots, onStartPlan, onCancelPlan }: Props) {
  const [name, setName] = useState("");
  const [nodes, setNodes] = useState<CanvasNode[]>([]);
  const [zoom, setZoom] = useState(0.9);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [connectingFrom, setConnectingFrom] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("Start with a bot, then connect its output to the next bot.");
  const [saving, setSaving] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const pinchDistance = useRef<number | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [viewportSize, setViewportSize] = useState({ w: 960, h: 640 });
  const planKey = activePlan?.plan.id || `draft-${draftKey}`;
  const readOnly = Boolean(activePlan);

  useEffect(() => {
    setName(activePlan?.plan.name || "");
    setNodes(activePlan ? nodesFromPlan(activePlan) : seededNodes(bots));
    setZoom(0.9);
    setDrag(null);
    setConnectingFrom(null);
    setError("");
    setSelectedNodeId(null);
    setNotice(activePlan ? `Loaded ${activePlan.nodes.length} bot${activePlan.nodes.length === 1 ? "" : "s"}. Select a node to inspect its output.` : "Start with a bot, then connect its output to the next bot.");
  }, [planKey, activePlan, bots]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const update = () => setViewportSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const edges = useMemo(
    () => nodes.flatMap((target) => target.after.map((sourceId) => ({ sourceId, targetId: target.id }))),
    [nodes],
  );

  const updateNode = (id: string, changes: Partial<CanvasNode>) => {
    if (readOnly) return;
    setNodes((current) => current.map((node) => (node.id === id ? { ...node, ...changes } : node)));
  };

  const removeNode = (id: string) => {
    if (readOnly) return;
    setNodes((current) =>
      current
        .filter((node) => node.id !== id)
        .map((node) => ({ ...node, after: node.after.filter((parent) => parent !== id) })),
    );
    if (connectingFrom === id) setConnectingFrom(null);
  };

  const beginDrag = (event: ReactPointerEvent<HTMLElement>, node: CanvasNode) => {
    if (readOnly) return;
    if ((event.target as HTMLElement).closest("button, input, select, textarea")) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ id: node.id, pointerX: event.clientX, pointerY: event.clientY, nodeX: node.x, nodeY: node.y });
  };

  const moveDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if (!drag) return;
    updateNode(drag.id, {
      x: clamp(drag.nodeX + (event.clientX - drag.pointerX) / zoom, 24, BOARD_WIDTH - NODE_WIDTH - 24),
      y: clamp(drag.nodeY + (event.clientY - drag.pointerY) / zoom, 70, BOARD_HEIGHT - NODE_HEIGHT - 24),
    });
  };

  const connectTo = (targetId: string) => {
    if (readOnly) return;
    if (!connectingFrom) {
      setError("Choose an output port first, then choose the next bot's input port.");
      setNotice("Connection needs a source: click an output dot first, then this input dot.");
      return;
    }
    if (introducesCycle(nodes, connectingFrom, targetId)) {
      setError("That arrow would create a cycle. Team workflows must remain a DAG.");
      setNotice("Blocked invalid arrow: workflows must stay acyclic so every bot has a deterministic start order.");
      setConnectingFrom(null);
      return;
    }
    const duplicate = nodes.find((node) => node.id === targetId)?.after.includes(connectingFrom);
    if (duplicate) {
      setError("Those two bots are already connected.");
      setNotice("No new arrow was added because that dependency already exists.");
      setConnectingFrom(null);
      return;
    }
    setNodes((current) =>
      current.map((node) =>
        node.id === targetId && !node.after.includes(connectingFrom)
          ? { ...node, after: [...node.after, connectingFrom] }
          : node,
      ),
    );
    setConnectingFrom(null);
    setError("");
    setNotice("Arrow added. The downstream bot will wait until its dependency completes.");
  };

  const reset = () => {
    setName("");
    setNodes([]);
    setZoom(0.9);
    setDrag(null);
    setConnectingFrom(null);
    setError("");
  };

  const runWorkflow = async () => {
    setError("");
    if (!name.trim()) return setError("Give this workflow a name.");
    if (!nodes.length) return setError("Add at least one bot node.");
    if (nodes.some((node) => !node.botName || !node.prompt.trim())) {
      return setError("Every node needs a bot and a focused instruction.");
    }
    const ids = new Map(nodes.map((node, index) => [node.id, `node-${index + 1}`]));
    const payloadNodes = nodes.map((node) => ({
      id: ids.get(node.id),
      bot_name: node.botName,
      prompt: node.prompt.trim(),
    }));
    const payloadEdges = edges.map((edge) => ({
      source: ids.get(edge.sourceId),
      target: ids.get(edge.targetId),
    }));
    setSaving(true);
    try {
      await api.createDelegation({ name: name.trim(), nodes: payloadNodes, edges: payloadEdges });
      reset();
      setNotice("Workflow started. It is now tracked in the workflow list.");
      onDone();
    } catch (exc) {
      setError((exc as Error).message || "Could not start workflow");
    } finally {
      setSaving(false);
    }
  };

  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const nodeOutput = selectedNode?.error || selectedNode?.result;
  const zoomBy = (delta: number) => setZoom((value) => clamp(value + delta, 0.35, 1.45));
  const boardZoomWidth = BOARD_WIDTH * zoom;
  const boardZoomHeight = BOARD_HEIGHT * zoom;
  const scaleWidth = Math.max(boardZoomWidth, viewportSize.w);
  const scaleHeight = Math.max(boardZoomHeight, viewportSize.h);
  const touchDistance = (touches: React.TouchList) => {
    const [first, second] = [touches.item(0), touches.item(1)];
    return first && second ? Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY) : null;
  };

  return (
      <section className="flow-studio" aria-label="Workflow canvas">
        <div className="flow-toolbar">
          <label className="flow-name">
            <span>Workflow</span>
            <input value={name} disabled={readOnly} onChange={(event) => setName(event.target.value)} maxLength={100} placeholder="Ship the release safely" />
          </label>
          <div className="flow-tool-group" aria-label="Canvas tools">
            {!readOnly && <button type="button" className="flow-tool primary" onClick={() => setNodes((current) => [...current, createNode(bots[0]?.name || "", 120 + current.length * 36, 130 + current.length * 32)])}>＋ Bot</button>}
            <button type="button" className="flow-tool" onClick={() => setNodes((current) => layoutNodes(current))}>Auto layout</button>
            <span className="flow-zoom">{Math.round(zoom * 100)}%</span>
          </div>
          {readOnly ? (
            activePlan?.plan.status === "paused" ? <button type="button" className="flow-run" onClick={() => onStartPlan?.(activePlan.plan.id)}>Start workflow</button>
              : !["succeeded", "failed", "cancelled"].includes(activePlan?.plan.status || "") && <button type="button" className="flow-run secondary" onClick={() => onCancelPlan?.(activePlan!.plan.id)}>Cancel workflow</button>
          ) : <button type="button" className="flow-run" disabled={saving} onClick={() => void runWorkflow()}>{saving ? "Starting…" : "Run workflow"}</button>}
        </div>

        <div className="flow-hint">
          <span className="flow-live-dot" /> {readOnly ? "Inspect the graph and select a bot for its result." : "Drag bots anywhere. Click an output dot, then an input dot, to draw an arrow."} Pinch or ⌘/Ctrl + wheel to zoom.
          {connectingFrom && <strong> Choose the next bot…</strong>}
        </div>

        <div
          ref={viewportRef}
          className="flow-viewport"
          style={{ "--flow-zoom": zoom } as CSSProperties}
          onPointerDown={(event) => { if (event.target === event.currentTarget) setConnectingFrom(null); }}
          onWheel={(event) => { if (event.ctrlKey || event.metaKey) { event.preventDefault(); zoomBy(event.deltaY < 0 ? 0.06 : -0.06); } }}
          onTouchStart={(event) => { pinchDistance.current = touchDistance(event.touches); }}
          onTouchMove={(event) => { const next = touchDistance(event.touches); if (next && pinchDistance.current) { event.preventDefault(); zoomBy((next - pinchDistance.current) / 360); pinchDistance.current = next; } }}
          onTouchEnd={() => { pinchDistance.current = null; }}
        >
          <div className="flow-scale" style={{ width: scaleWidth, height: scaleHeight, minWidth: "100%", minHeight: "100%" }}>
            <div className="flow-canvas" style={{ width: BOARD_WIDTH, height: BOARD_HEIGHT, transform: `scale(${zoom})` }}>
              <svg className="flow-edges" width={BOARD_WIDTH} height={BOARD_HEIGHT} aria-hidden="true">
                <defs>
                  <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" />
                  </marker>
                </defs>
                {edges.map((edge) => {
                  const source = nodes.find((node) => node.id === edge.sourceId);
                  const target = nodes.find((node) => node.id === edge.targetId);
                  if (!source || !target) return null;
                  return <path key={`${edge.sourceId}:${edge.targetId}`} d={edgePath(source, target)} markerEnd="url(#flow-arrow)" />;
                })}
              </svg>

              {nodes.map((node, index) => (
                <article
                  key={node.id}
                  className={`flow-node${drag?.id === node.id ? " dragging" : ""}`}
                  style={{ left: node.x, top: node.y, width: NODE_WIDTH, minHeight: NODE_HEIGHT }}
                  onClick={() => setSelectedNodeId(node.id)}
                >
                  <button
                    type="button"
                    className={`flow-port input${connectingFrom ? " ready" : ""}`}
                    aria-label={`Connect into node ${index + 1}`}
                    onClick={() => connectTo(node.id)}
                  />
                  <header
                    className="flow-node-header"
                    onPointerDown={(event) => beginDrag(event, node)}
                    onPointerMove={moveDrag}
                    onPointerUp={() => setDrag(null)}
                    onPointerCancel={() => setDrag(null)}
                  >
                    <span className="flow-node-index">{String(index + 1).padStart(2, "0")}</span>
                    <span className="flow-node-kind">KYN bot</span>
                    <span className="flow-node-grip" aria-hidden>⠿</span>
                    {!readOnly && <button type="button" className="flow-node-remove" aria-label={`Remove node ${index + 1}`} onClick={() => removeNode(node.id)}>×</button>}
                  </header>
                  <div className="flow-node-body">
                    <label>
                      <span>Agent</span>
                      <select value={node.botName} disabled={readOnly} onChange={(event) => updateNode(node.id, { botName: event.target.value })}>
                        <option value="">Choose bot</option>
                        {bots.map((bot) => <option key={bot.name} value={bot.name}>{bot.name}</option>)}
                      </select>
                    </label>
                    <label>
                      <span>Instruction</span>
                      <textarea value={node.prompt} disabled={readOnly} onChange={(event) => updateNode(node.id, { prompt: event.target.value })} rows={4} placeholder="One focused outcome for this bot…" />
                    </label>
                    <div className="flow-node-meta">
                      {node.after.length ? `Waits for ${node.after.length} node${node.after.length === 1 ? "" : "s"}` : "Runs immediately"}
                    </div>
                  </div>
                  {!readOnly && <button
                    type="button"
                    className={`flow-port output${connectingFrom === node.id ? " active" : ""}`}
                    aria-label={`Connect from node ${index + 1}`}
                    onClick={() => { setConnectingFrom(node.id); setError(""); }}
                  />}
                </article>
              ))}

              {!readOnly && nodes.length === 0 && (
                <button type="button" className="flow-empty" onClick={() => setNodes([createNode(bots[0]?.name || "", 120, 140)])}>
                  <span>＋</span>
                  Drop your first bot onto the canvas
                </button>
              )}
            </div>
          </div>
        </div>

        <footer className="flow-footer">
          <div className="flow-status-copy">
            <span className={error ? "flow-status-badge error" : "flow-status-badge"}>{error ? "Blocked" : "Canvas event"}</span>
            <p role="alert">{error || notice}</p>
          </div>
          {selectedNode ? <div className="flow-output"><strong>{selectedNode.botName}</strong><span>{selectedNode.status || "draft"}</span><p>{nodeOutput ? (typeof nodeOutput === "string" ? nodeOutput : JSON.stringify(nodeOutput)) : "No output recorded yet."}</p></div> : <div className="flow-summary"><strong>{nodes.length}</strong> bots · <strong>{edges.length}</strong> arrows · roots run in parallel</div>}
        </footer>
      </section>
  );
}
