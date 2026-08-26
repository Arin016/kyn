import { progress, scenes, sec, WORKFLOW_NAME } from "./timeline";

const NODE_W = 280;
const NODE_H = 230;
const BOARD_W = 1440;
const BOARD_H = 820;

export type WorkflowNode = {
  id: string;
  index: number;
  botName: string;
  prompt: string;
  x: number;
  y: number;
  after: string[];
  status?: "draft" | "pending" | "running" | "succeeded" | "failed";
  visible: boolean;
};

export type WorkflowSnapshot = {
  name: string;
  zoom: number;
  nodes: WorkflowNode[];
  edges: Array<{ sourceId: string; targetId: string; drawProgress: number }>;
  connectingFrom: string | null;
  connectTargetReady: boolean;
  selectedNodeId: string | null;
  notice: string;
  statusLine: string;
  runHot: boolean;
  planStatus: "draft" | "running" | "succeeded";
  showReviewerOutput: boolean;
};

const N1 = "wf-n1";
const N2 = "wf-n2";
const N3 = "wf-n3";

function edgePath(
  source: { x: number; y: number },
  target: { x: number; y: number },
): string {
  const sx = source.x + NODE_W;
  const sy = source.y + 94;
  const tx = target.x;
  const ty = target.y + 94;
  const bend = Math.max(80, Math.abs(tx - sx) * 0.45);
  return `M ${sx} ${sy} C ${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`;
}

export function workflowEdgePath(sourceId: string, targetId: string, nodes: WorkflowNode[]): string | null {
  const source = nodes.find((n) => n.id === sourceId);
  const target = nodes.find((n) => n.id === targetId);
  if (!source || !target) return null;
  return edgePath(source, target);
}

export function buildWorkflowSnapshot(frame: number): WorkflowSnapshot {
  const t = frame - scenes.workflow.start;
  const local = Math.max(0, t);

  const showThird = local >= sec(2.5);
  const connectPhase = local >= sec(4) && local < sec(7);
  const runPhase = local >= sec(9);
  const selectReviewer = local >= sec(14);

  const n1Status: WorkflowNode["status"] = runPhase
    ? local < sec(11)
      ? "running"
      : "succeeded"
    : "draft";
  const n2Status: WorkflowNode["status"] = runPhase
    ? local < sec(11)
      ? "pending"
      : local < sec(13)
        ? "running"
        : "succeeded"
    : "draft";
  const n3Status: WorkflowNode["status"] = runPhase
    ? local < sec(13)
      ? "pending"
      : local < sec(16)
        ? "running"
        : "succeeded"
    : showThird
      ? "draft"
      : undefined;

  const nodes: WorkflowNode[] = [
    {
      id: N1,
      index: 1,
      botName: "triage",
      prompt: "Scan README and architecture docs for launch risks.",
      x: 90,
      y: 150,
      after: [],
      status: n1Status,
      visible: true,
    },
    {
      id: N2,
      index: 2,
      botName: "builder",
      prompt: "Ship the smallest verified patch in an isolated worktree.",
      x: 520,
      y: 150,
      after: [N1],
      status: n2Status,
      visible: true,
    },
    {
      id: N3,
      index: 3,
      botName: "reviewer",
      prompt: "Independent review before handoff. Flag any security regressions.",
      x: 900,
      y: 150,
      after: [N2],
      status: n3Status,
      visible: showThird,
    },
  ].filter((n) => n.visible);

  const edge1Draw = 1;
  const edge2Draw = connectPhase
    ? progress(local, sec(4), sec(6.5))
    : showThird && local >= sec(6.5)
      ? 1
      : 0;

  const edges = [
    { sourceId: N1, targetId: N2, drawProgress: edge1Draw },
    ...(showThird ? [{ sourceId: N2, targetId: N3, drawProgress: edge2Draw }] : []),
  ];

  const zoom = runPhase
    ? 0.95 + 0.04
    : showThird
      ? 0.88 + 0.07 * Math.min(1, local / sec(2))
      : 0.88;

  let notice = "Drag bots anywhere. Click an output dot, then an input dot, to draw an arrow.";
  if (connectPhase && local < sec(5)) {
    notice = "Arrow added. The downstream bot will wait until its dependency completes.";
  } else if (connectPhase) {
    notice = "Three specialists: triage → builder → reviewer. Parallel roots when dependencies allow.";
  } else if (runPhase && !selectReviewer) {
    notice = "Independent tasks run in parallel. Dependent bots wait for upstream results.";
  } else if (selectReviewer) {
    notice = "Select a bot node to read its recorded output in the event panel.";
  }

  const statusLine = runPhase
    ? selectReviewer
      ? "succeeded · outputs below"
      : "running · outputs below"
    : "Draft · not started";

  return {
    name: local >= sec(8) ? WORKFLOW_NAME : "",
    zoom,
    nodes,
    edges,
    connectingFrom: connectPhase && local >= sec(4) && local < sec(5.2) ? N2 : null,
    connectTargetReady: connectPhase && local >= sec(4.8),
    selectedNodeId: selectReviewer ? N3 : null,
    notice,
    statusLine,
    runHot: local >= sec(8) && local < sec(9.2),
    planStatus: runPhase ? (selectReviewer ? "succeeded" : "running") : "draft",
    showReviewerOutput: selectReviewer,
  };
}

export type WorkflowCursorPlan = {
  x: number;
  y: number;
  clicking: boolean;
  visible: boolean;
  clickFrame: number;
};

/** Screen coords inside 1920×1080 demo-stage. */
function portCoords(node: WorkflowNode, side: "out" | "in", zoom: number): { x: number; y: number } {
  const rail = 260 + 220;
  const top = 100 + 50 + 32;
  const px = side === "out" ? node.x + NODE_W : node.x;
  const py = node.y + 94;
  return {
    x: rail + 17 + px * zoom + (side === "out" ? 8 : -8),
    y: top + py * zoom,
  };
}

export function workflowCursorPlan(frame: number): WorkflowCursorPlan {
  const local = frame - scenes.workflow.start;
  const snap = buildWorkflowSnapshot(frame);
  const n2 = snap.nodes.find((n) => n.id === N2);
  const n3 = snap.nodes.find((n) => n.id === N3);
  const runBtn = { x: 1680, y: 118 };
  const reviewerNode = { x: 1180, y: 320 };

  if (local < sec(1.5)) {
    const t = progress(local, sec(0.3), sec(1.2));
    const from = { x: 1580, y: 48 };
    const to = { x: 130, y: 200 };
    return {
      x: from.x + (to.x - from.x) * t,
      y: from.y + (to.y - from.y) * t,
      clicking: local >= sec(1.1) && local < sec(1.5),
      visible: true,
      clickFrame: scenes.workflow.start + sec(1.1),
    };
  }

  if (local < sec(4) && n2) {
    const out = portCoords(n2, "out", snap.zoom);
    const t = progress(local, sec(2), sec(3.5));
    return {
      x: 400 + (out.x - 400) * t,
      y: 280 + (out.y - 280) * t,
      clicking: false,
      visible: true,
      clickFrame: 0,
    };
  }

  if (local < sec(7) && n2 && n3) {
    const out = portCoords(n2, "out", snap.zoom);
    const inp = portCoords(n3, "in", snap.zoom);
    if (local < sec(5.2)) {
      return {
        x: out.x,
        y: out.y,
        clicking: local >= sec(4) && local < sec(4.6),
        visible: true,
        clickFrame: scenes.workflow.start + sec(4),
      };
    }
    const t = progress(local, sec(5.2), sec(6.5));
    return {
      x: out.x + (inp.x - out.x) * t,
      y: out.y + (inp.y - out.y) * t,
      clicking: local >= sec(6.3) && local < sec(6.8),
      visible: true,
      clickFrame: scenes.workflow.start + sec(6.3),
    };
  }

  if (local < sec(9)) {
    const t = progress(local, sec(7.5), sec(8.8));
    return {
      x: 1100 + (runBtn.x - 1100) * t,
      y: 300 + (runBtn.y - 300) * t,
      clicking: local >= sec(8.6) && local < sec(9.2),
      visible: true,
      clickFrame: scenes.workflow.start + sec(8.6),
    };
  }

  if (local < sec(14)) {
    return { x: runBtn.x, y: runBtn.y, clicking: false, visible: local < sec(12), clickFrame: 0 };
  }

  const t = progress(local, sec(14), sec(15.5));
  return {
    x: runBtn.x + (reviewerNode.x - runBtn.x) * t,
    y: runBtn.y + (reviewerNode.y - runBtn.y) * t,
    clicking: false,
    visible: true,
    clickFrame: 0,
  };
}

export const WORKFLOW_BOARD = { width: BOARD_W, height: BOARD_H, nodeW: NODE_W, nodeH: NODE_H };
