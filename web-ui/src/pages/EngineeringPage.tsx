import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { AriGlyph } from "../components/AriGlyph";

type Step = {
  title: string;
  body: string;
  cite: string;
  mark?: boolean;
};

const STEPS: Step[] = [
  {
    title: "A builder works in an isolated task workspace",
    body:
      "The selected builder bot runs in a Git worktree cut from your repo. Your current checkout stays put while Ari records the task branch and changed files.",
    cite: "workspaces.py",
  },
  {
    title: "Your checks decide whether the work passes",
    body:
      "The commands you provide, such as pytest or mypy, run inside the worktree as direct arguments. Each check has a timeout and its result is recorded with the task.",
    cite: "coding_workflow.py",
  },
  {
    title: "Bounded repair",
    body:
      "When a check fails, Ari can give the builder the failure output and a bounded chance to repair it. You choose the repair limit for the task.",
    cite: "coding_workflow.py",
  },
  {
    title: "A different bot reads the diff",
    body:
      "A different named bot reviews the resulting change with its own engine and policy. Ari checks for unexpected changes during review and keeps the findings with the task.",
    cite: "coding_lifecycle.py",
  },
  {
    title: "You approve, or nothing lands",
    body:
      "Review the findings and diff, then approve the handoff before merging the reviewed task into its base branch. Ari does not open pull requests or publish changes.",
    cite: "coding_lifecycle.py",
    mark: true,
  },
];

const SUBSYSTEMS: { area: string; role: string; file: string }[] = [
  {
    area: "Engine",
    role: "Runs one named bot on Kiro, OpenCode, or Codex through its ACP-compatible process. Per-bot FIFO workers keep each bot's turns ordered.",
    file: "engine.py",
  },
  {
    area: "Runtime",
    role: "Spawns and supervises the selected ACP engine process, streams structured events, and keeps subprocess output separate from the protocol.",
    file: "runtime.py",
  },
  {
    area: "Session",
    role: "Owns the ACP conversation lifecycle and normalizes engine events so chat, approvals, and run history share one interface.",
    file: "session.py",
  },
  {
    area: "Governance",
    role: "Per-bot tool policy, quotas, durable approval decisions, and an audit log that records decisions without raw tool arguments.",
    file: "governance.py",
  },
  {
    area: "Plugins",
    role: "MCP catalogue and registry with per-bot bindings. Secrets resolve from environment references only when a session launches.",
    file: "plugins.py",
  },
  {
    area: "Workspaces",
    role: "Isolated Git worktrees and task branches with lease tracking, changed-file manifests, review, and explicit merge or abandon actions.",
    file: "workspaces.py",
  },
  {
    area: "Coding lifecycle",
    role: "Builder, checks, bounded repair, reviewer, and human handoff stages with idempotent state transitions.",
    file: "coding_lifecycle.py",
  },
  {
    area: "Delegation",
    role: "Multi-bot DAGs with bounded fan-out and depth. Conversational host tools and the Workflow playground compile to the same durable graph; saved plans, validation events, and per-node outputs make execution inspectable.",
    file: "delegation.py · control_mcp.py",
  },
  {
    area: "Interactions",
    role: "Durable, single-decision human gates. Reload-safe control-room cards and Telegram inline callbacks; no blanket run trust.",
    file: "interactions.py",
  },
  {
    area: "Channels",
    role: "Authenticated event intake from Slack, GitHub, WhatsApp Cloud API, normalized email, signed webhooks, and Telegram polling.",
    file: "channels.py",
  },
  {
    area: "Memory",
    role: "Append-only shared-memory ledger per bot. Bounded relevance-and-recency retrieval across surfaces. Original messages never rewritten.",
    file: "memory.py",
  },
];

const ROADMAP = [
  {
    title: "Pull request publishing",
    body:
      "A reviewed task can merge into its local base branch after approval. Opening pull requests and coordinating CI from a connected provider are not part of Ari yet.",
  },
  {
    title: "People and organization controls",
    body:
      "Remote access can use a bearer token, but Ari does not yet provide user accounts, organization tenancy, SSO, or team-wide administration.",
  },
  {
    title: "Asynchronous bot conversations",
    body:
      "Bots can call a named bot for a focused result or run through a durable team plan. Always-on asynchronous bot mailboxes are not available yet.",
  },
  {
    title: "More native connectors",
    body:
      "Email currently arrives through a normalized signed webhook. A first-party Gmail sync and a browser-control engine are not available yet.",
  },
];

function useSectionScrollProgress(sectionRef: React.RefObject<HTMLElement | null>) {
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    const scroller = document.querySelector(".ed") as HTMLElement | null;
    if (!scroller || !sectionRef.current) return;
    const compute = () => {
      const section = sectionRef.current;
      if (!section) return;
      const sRect = section.getBoundingClientRect();
      const cRect = scroller.getBoundingClientRect();
      const top = sRect.top - cRect.top;
      const vh = cRect.height;
      const start = vh * 0.65;
      const end = -sRect.height + vh * 0.35;
      const p = start === end ? 1 : (start - top) / (start - end);
      setProgress(Math.max(0, Math.min(1, p)));
    };
    scroller.addEventListener("scroll", compute, { passive: true });
    window.addEventListener("resize", compute);
    compute();
    return () => {
      scroller.removeEventListener("scroll", compute);
      window.removeEventListener("resize", compute);
    };
  }, [sectionRef]);
  return progress;
}

function LifecycleStep({ step, index }: { step: Step; index: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(false);
  useEffect(() => {
    const el = ref.current;
    const scroller = document.querySelector(".ed") as HTMLElement | null;
    if (!el || !scroller) return;
    const observer = new IntersectionObserver(
      ([entry]) => setActive(entry.isIntersecting),
      { root: scroller, rootMargin: "-35% 0px -35% 0px", threshold: 0 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <motion.div
      ref={ref}
      className={`ed-step${active ? " is-active" : ""}`}
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{ duration: 0.5, delay: index * 0.05, ease: [0.22, 1, 0.36, 1] }}
    >
      <div className="ed-step-node" aria-hidden>
        {String(index + 1).padStart(2, "0")}
      </div>
      <div className="ed-step-body">
        <div className="ed-step-title-row">
          <h3 className="ed-h3">{step.title}</h3>
          {step.mark && <span className="ed-step-mark" aria-hidden>◆</span>}
        </div>
        <span className="ed-step-cite">src/kyn/{step.cite}</span>
        <p className="ed-body">{step.body}</p>
      </div>
    </motion.div>
  );
}

function Reveal({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{ duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

interface Props {
  onEnterConsole: () => void;
  onBackToLanding: () => void;
}

export default function EngineeringPage({ onEnterConsole, onBackToLanding }: Props) {
  const [scrolled, setScrolled] = useState(false);
  const lifecycleRef = useRef<HTMLElement>(null);
  const railProgress = useSectionScrollProgress(lifecycleRef);

  useEffect(() => {
    const root = document.querySelector(".ed");
    if (!root) return;
    const onScroll = () => setScrolled((root as HTMLElement).scrollTop > 8);
    root.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => root.removeEventListener("scroll", onScroll);
  }, []);

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="ed">
      <a className="ed-skip" href="#main">Skip to content</a>

      <header className={`ed-nav${scrolled ? " scrolled" : ""}`}>
        <div className="ed-container ed-nav-inner">
          <button
            type="button"
            className="ed-wordmark"
            onClick={onBackToLanding}
            aria-label="Ari — home"
          >
            <AriGlyph className="glyph" size={26} tone="ink" />
            Ari
          </button>
          <nav className="ed-nav-links" aria-label="How Ari works">
            <button type="button" onClick={() => scrollTo("protocol")}>Engines</button>
            <button type="button" onClick={() => scrollTo("lifecycle")}>Tasks</button>
            <button type="button" onClick={() => scrollTo("map")}>Product map</button>
            <button type="button" onClick={() => scrollTo("roadmap")}>Current boundaries</button>
            <button type="button" className="ed-btn ed-btn-primary" onClick={onEnterConsole}>
              Open the console
            </button>
          </nav>
        </div>
      </header>

      <main id="main">
        {/* HERO */}
        <section className="ed-container ed-hero ed-hero-eng">
          <motion.p
            className="ed-eyebrow"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            How Ari works
          </motion.p>
          <motion.h1
            className="ed-hero-h1 ed-hero-h1-eng"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
          >
            One crew. Three engines. A shared place to work.
          </motion.h1>
          <motion.p
            className="ed-lead"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.16 }}
          >
            Choose Kiro, OpenCode, or Codex for each bot. Ari keeps the conversation, work queue,
            connected tools, handoffs, and review steps together, while each engine remains in
            charge of its own reasoning and tool execution.
          </motion.p>
        </section>

        {/* PROTOCOL TRACE */}
        <section id="protocol" className="ed-section" style={{ paddingTop: 0 }}>
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">One workspace · three engines</p>
              <h2 className="ed-h2">Pick an engine for each bot. Keep the work together.</h2>
              <p className="ed-body ed-body-lead">
                Ari launches each selected engine through its ACP-compatible command. The engine
                handles its models and tools; Ari handles named bots, conversations, approvals,
                work queues, channels, and the context carried between engines.
              </p>
            </Reveal>

            <Reveal delay={0.1}>
              <div className="ed-install">
                <div className="ed-install-head">
                  <span className="dots" aria-hidden>
                    <span /><span /><span />
                  </span>
                  <span className="ed-install-path">ACP protocol trace</span>
                  <span className="ed-install-label">wire</span>
                </div>
                <pre>
                  <code>
{`choose engine  `}<span className="cmd">Kiro | OpenCode | Codex</span>{`
  → launch its ACP process
  → initialize
  → session/new  `}<span className="cmt">{`{ project, configured tools }`}</span>{`
  → session/prompt        `}<span className="cmt">{`{ sessionId, prompt: [...] }`}</span>{`
  ← normalized events     `}<span className="cmt">{`(text, tool activity, usage)`}</span>{`
  ← permission request    `}<span className="cmt">{`(handled by bot policy)`}</span>{`
  → `}<span className="path">approve / reject</span>{`
  ← result and run record`}
                  </code>
                </pre>
              </div>
            </Reveal>

            <Reveal delay={0.18}>
              <div className="ed-install-notes">
                <div>
                  <p className="ed-eyebrow">What Ari tracks</p>
                  <p className="ed-body">
                    Accepted work gets a durable record. Each bot's turns stay ordered while
                    different bots can run concurrently. Pending approvals and task reviews remain
                    visible in the work inbox.
                  </p>
                </div>
                <div>
                  <p className="ed-eyebrow">What stays with each engine</p>
                  <p className="ed-body">
                    Model access, reasoning, and native tool execution. Ari provides the continuity
                    and review experience around those engines without replacing their harnesses.
                  </p>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* CODING LIFECYCLE */}
        <section id="lifecycle" ref={lifecycleRef} className="ed-section" style={{ paddingTop: 0 }}>
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Verified coding</p>
              <h2 className="ed-h2">A code change should come back with evidence.</h2>
              <p className="ed-body ed-body-lead">
                A coding task moves through isolation, your checks, bounded repair, and an
                independent review. You inspect the findings and diff, then approve before the
                reviewed task is merged into its base branch.
              </p>
            </Reveal>

            <div className="ed-lifecycle-wrap">
              <div className="ed-lifecycle-rail" aria-hidden>
                <div
                  className="ed-lifecycle-rail-fill"
                  style={{ transform: `scaleY(${railProgress})` }}
                />
              </div>
              {STEPS.map((step, index) => (
                <LifecycleStep key={step.title} step={step} index={index} />
              ))}
            </div>

            <Reveal delay={0.15}>
              <div className="ed-install" style={{ marginTop: "3rem" }}>
                <div className="ed-install-head">
                  <span className="dots" aria-hidden>
                    <span /><span /><span />
                  </span>
                  <span className="ed-install-path">POST /api/coding-executions/&lbrace;id&rbrace;/approve</span>
                  <span className="ed-install-label">the handoff</span>
                </div>
                <pre>
                  <code>
{`$ `}<span className="cmd">curl</span>{` -X POST http://127.0.0.1:8765/api/coding-executions/exec_9f2c/approve \\
    -H 'Content-Type: application/json' \\
    -d `}<span className="path">{`'{"expected_version": 4}'`}</span>{`

`}<span className="cmt">{`# 200 OK`}</span>{`
{
  "id":               "exec_9f2c",
  "status":           `}<span className="path">"ready"</span>{`,
  "version":          5,
  "spec_sha256":      "b2a1…c7e9",
  "workspace_run_id": "ws_9f2c",
  "result": { "reviewer_bot": "critic", "checks_passed": 2 }
}`}
                  </code>
                </pre>
              </div>
            </Reveal>
          </div>
        </section>

        {/* SUBSYSTEM MAP */}
        <section id="map" className="ed-band">
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Product architecture</p>
              <h2 className="ed-h2">The features are durable because the state is.</h2>
              <p className="ed-body ed-body-lead">
                Every product promise maps to a small subsystem under{" "}
                <code className="ed-inline-code">src/kyn/</code>. Everything durable lives in a
                local SQLite database under <code className="ed-inline-code">~/.ari/</code>,
                while secrets remain environment references resolved only when a session starts.
              </p>
            </Reveal>

            <Reveal delay={0.08}>
              <div className="ed-map">
                {SUBSYSTEMS.map((subsystem) => (
                  <div key={subsystem.area} className="ed-map-row">
                    <div className="ed-map-area">
                      <span className="ed-map-title">{subsystem.area}</span>
                      <span className="ed-map-file">src/kyn/{subsystem.file}</span>
                    </div>
                    <p className="ed-map-role">{subsystem.role}</p>
                  </div>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        {/* ROADMAP */}
        <section id="roadmap" className="ed-section">
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Current boundaries</p>
              <h2 className="ed-h2">Know what Ari can do today.</h2>
              <p className="ed-body ed-body-lead">
                Ari supports local use and can be deployed remotely. The capabilities below are
                not included yet, so you can see where the current product stops.
              </p>
            </Reveal>

            <div className="ed-scenes" style={{ marginTop: "3rem" }}>
              {ROADMAP.map((item, index) => (
                <Reveal key={item.title} delay={0.05 * index}>
                  <article className="ed-scene">
                    <h3 className="ed-scene-title" style={{ fontSize: "1.25rem" }}>
                      {item.title}
                    </h3>
                    <p className="ed-scene-body">{item.body}</p>
                  </article>
                </Reveal>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="ed-footer">
        <div className="ed-container">
          <div className="ed-footer-grid">
            <div className="ed-footer-col">
              <div className="ed-footer-mark">
                <AriGlyph className="glyph" size={22} tone="ink" />
                Ari
              </div>
              <p className="ed-footer-tag">
                A shared workspace around Kiro, OpenCode, and Codex. Each engine remains in charge
                of its own model access and tool execution.
              </p>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Product</p>
              <ul>
                <li><button type="button" onClick={onEnterConsole}>Console</button></li>
                <li><button type="button" onClick={onBackToLanding}>Landing</button></li>
              </ul>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Engineering</p>
              <ul>
                <li><button type="button" onClick={() => scrollTo("protocol")}>Protocol</button></li>
                <li><button type="button" onClick={() => scrollTo("lifecycle")}>Lifecycle</button></li>
                <li><button type="button" onClick={() => scrollTo("map")}>Subsystems</button></li>
                <li><button type="button" onClick={() => scrollTo("roadmap")}>Current boundaries</button></li>
              </ul>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Safety</p>
              <ul>
                <li>Approvals answered, never dropped</li>
                <li>Secrets stay in env vars</li>
                <li>Audit is payload-free</li>
                <li>Human approval before task merge</li>
              </ul>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Runtime</p>
              <ul>
                <li>Loopback binding by default</li>
                <li>SQLite under ~/.ari/</li>
                <li>One controller per data dir</li>
                <li>Telegram polled, not webhooked</li>
              </ul>
            </div>
          </div>
          <div className="ed-footer-bottom">
            <span className="ed-footer-fine">
              Ari is an independent product. Kiro, OpenCode, and Codex are their respective owners' products.
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
