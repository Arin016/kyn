import { useEffect, useState } from "react";
import api from "../../api";
import type { Bot, DelegationDetail, DelegationPlan } from "../../types";
import { WorkflowStudio } from "../dialogs/WorkflowStudio";
import { demoDelegationDetail } from "../../lib/demoConsole";

interface Props {
  bots: Bot[];
  plans: DelegationPlan[];
  demoMode?: boolean;
  onRefresh: () => void;
  onStart: (plan: DelegationPlan) => void;
  onCancel: (plan: DelegationPlan) => void;
  onBackToChat: () => void;
}

const terminal = new Set(["succeeded", "failed", "cancelled"]);

export function WorkflowPlayground({ bots, plans, demoMode = false, onRefresh, onStart, onCancel, onBackToChat }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DelegationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [draftKey, setDraftKey] = useState(0);

  const selectedPlan = plans.find((plan) => plan.id === selectedId) || null;

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setLoadError("");
      return;
    }
    if (demoMode) {
      const mock = demoDelegationDetail(selectedId);
      setDetail(mock);
      setLoadError(mock ? "" : "Demo workflow not found.");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError("");
    const load = () => void api.delegation(selectedId)
      .then((payload) => { if (!cancelled) setDetail(payload); })
      .catch((error: Error) => { if (!cancelled) setLoadError(error.message || "Could not load this workflow."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    load();
    const timer = window.setInterval(load, 2500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [selectedId, demoMode]);

  const selectDraft = () => {
    setSelectedId(null);
    setDetail(null);
    setDraftKey((value) => value + 1);
  };

  const selectPlan = (plan: DelegationPlan) => setSelectedId(plan.id);

  return (
    <section className="workflow-page" aria-label="Workflow playground">
      <aside className="workflow-rail" aria-label="Workflows">
        <div className="workflow-rail-header">
          <div>
            <p className="eyebrow">Control room</p>
            <h2>Workflows</h2>
          </div>
          <button type="button" className="workflow-new" onClick={selectDraft}>＋ New</button>
        </div>
        <p className="workflow-rail-copy">Compose agents, watch their state, and inspect each bot’s output in one place.</p>
        <div className="workflow-list" role="list">
          <button type="button" className={`workflow-list-item draft${!selectedId ? " selected" : ""}`} onClick={selectDraft}>
            <span className="workflow-list-symbol">＋</span>
            <span><strong>Untitled workflow</strong><small>New editable canvas</small></span>
          </button>
          {[...plans].reverse().map((plan) => (
            <button key={plan.id} type="button" className={`workflow-list-item${selectedId === plan.id ? " selected" : ""}`} onClick={() => selectPlan(plan)}>
              <span className={`workflow-plan-dot ${plan.status}`} />
              <span><strong>{plan.name}</strong><small>{plan.status.replaceAll("_", " ")} · {plan.max_fanout ?? 1} parallel · depth {plan.max_depth ?? 1}</small></span>
            </button>
          ))}
          {plans.length === 0 && <p className="workflow-list-empty">No saved workflows yet. Build the first one here.</p>}
        </div>
        <button type="button" className="workflow-back" onClick={onBackToChat}>← Back to conversation</button>
      </aside>
      <div className="workflow-stage">
        <header className="workflow-stage-header">
          <div>
            <p className="eyebrow">{selectedPlan ? "Saved workflow" : "New workflow"}</p>
            <h1>{selectedPlan?.name || "Build a team"}</h1>
          </div>
          <div className="workflow-stage-state">
            {loading ? "Loading graph…" : loadError || (selectedPlan ? `${selectedPlan.status.replaceAll("_", " ")} · outputs below` : "Draft · not started")}
          </div>
        </header>
        {loadError ? <div className="workflow-load-error" role="alert">{loadError}</div> : (
          <WorkflowStudio
            bots={bots}
            activePlan={detail}
            draftKey={draftKey}
            demoMode={demoMode}
            onDone={() => { onRefresh(); selectDraft(); }}
            onStartPlan={(id) => { if (selectedPlan && selectedPlan.id === id) onStart(selectedPlan); }}
            onCancelPlan={(id) => { if (selectedPlan && selectedPlan.id === id) onCancel(selectedPlan); }}
          />
        )}
        {selectedPlan && !loading && terminal.has(selectedPlan.status) && <p className="workflow-terminal-note">This workflow is complete. Its graph and recorded bot outputs remain available for review.</p>}
      </div>
    </section>
  );
}
