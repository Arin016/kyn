import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { KiroGlyph } from "../components/KiroGlyph";

type Step = {
  title: string;
  body: string;
  cite: string;
  mark?: boolean;
};

const STEPS: Step[] = [
  {
    title: "Builder in a detached worktree",
    body:
      "The named builder bot writes into a Git worktree cut from your repo. Your checkout does not move. Artifacts are hashed as they land — capped at 128 files, 25 MiB each, 100 MiB total.",
    cite: "workspaces.py",
  },
  {
    title: "Deterministic checks by your commands",
    body:
      "The checks you gave — pytest, mypy, whatever — run inside the worktree by direct argv, not through a tool call. Timeouts are per-check and aggregate. Nothing runs under a shell.",
    cite: "coding_workflow.py",
  },
  {
    title: "Bounded repair",
    body:
      "On failure, a repair turn feeds Kiro the exact output of the failed check. The loop caps at a number you set at execution time. Hard-limited to three.",
    cite: "coding_workflow.py",
  },
  {
    title: "A different bot reads the diff",
    body:
      "The reviewer is a separate named bot with its own policy. It reads the artifact manifest, not the writer's plan. If the reviewer touches a file, the SHA-256 changes and the mutation is flagged.",
    cite: "coding_lifecycle.py",
  },
  {
    title: "You approve, or nothing lands",
    body:
      "Nothing merges, pushes, opens a pull request, or replies until you approve the handoff. The worktree is retained. Cleanup is a separate call that only removes clean state.",
    cite: "coding_lifecycle.py",
    mark: true,
  },
];

const SUBSYSTEMS: { area: string; role: string; file: string }[] = [
  {
    area: "Engine",
    role: "Multiplexes many logical Kiro sessions over one kiro-cli acp subprocess. Per-bot FIFO workers with expiring durable leases.",
    file: "engine.py",
  },
  {
    area: "Runtime",
    role: "Spawns and supervises kiro-cli acp. Newline-delimited JSON-RPC 2.0 over stdin/stdout. Untrusted framing, drained stderr.",
    file: "runtime.py",
  },
  {
    area: "Session",
    role: "Owns the ACP conversation lifecycle. initialize, session/new, session/prompt, session/update, session/request_permission.",
    file: "session.py",
  },
  {
    area: "Governance",
    role: "Per-bot approval policy (ask, deny, allow-list). Atomic quota leases. Payload-free audit log — decisions only, never arguments.",
    file: "governance.py",
  },
  {
    area: "Plugins",
    role: "MCP registry with per-bot bindings. Secret values never persist; only environment-variable references. Resolution happens at session launch.",
    file: "plugins.py",
  },
  {
    area: "Workspaces",
    role: "Detached Git worktrees per run with heartbeat leases. Artifact manifests hashed with SHA-256. Explicit clean-only cleanup.",
    file: "workspaces.py",
  },
  {
    area: "Coding lifecycle",
    role: "Builder / checks / repair / reviewer state machine with idempotency and mutation detection. Human handoff is the only completion path.",
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
    role: "Signature-verified ingest from Slack, GitHub, WhatsApp, email, and generic webhooks. Telegram polls and returns actionable approval buttons without a public URL.",
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
    title: "A reviewer-driven publisher",
    body:
      "Binary patch bundles, a separately approved publisher that opens pull requests and drives CI repair. Merge stays human-only.",
  },
  {
    title: "Auth, org boundaries, budgets",
    body:
      "Right now the daemon binds to loopback with no authentication layer. The next chapter is proper multi-tenancy, SSO, and metered provider budgets per bot.",
  },
  {
    title: "Bot-to-bot mailboxes",
    body:
      "Delegation is one-directional today. Persistent inter-bot queues would let bots subscribe to each other's completions without a plan graph.",
  },
  {
    title: "Native Gmail, computer-use",
    body:
      "Email is a normalized webhook contract. A first-party Gmail OAuth synchronizer and a browser/computer-use provider are on the list.",
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
        <span className="ed-step-cite">src/kiro_bot/{step.cite}</span>
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
            aria-label="KYN — home"
          >
            <KiroGlyph className="glyph" size={26} />
            KYN
          </button>
          <nav className="ed-nav-links" aria-label="Engineering">
            <button type="button" onClick={() => scrollTo("protocol")}>Protocol</button>
            <button type="button" onClick={() => scrollTo("lifecycle")}>Lifecycle</button>
            <button type="button" onClick={() => scrollTo("map")}>Map</button>
            <button type="button" onClick={() => scrollTo("roadmap")}>Roadmap</button>
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
            Under the surface
          </motion.p>
          <motion.h1
            className="ed-hero-h1 ed-hero-h1-eng"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
          >
            Kiro does the work. This system makes it durable.
          </motion.h1>
          <motion.p
            className="ed-lead"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.16 }}
          >
            KYN does not replace the Kiro agent harness. It gives Kiro a durable identity,
            routes real work to it, preserves the state around each job, and enforces the boundaries
            the model cannot be trusted to remember on its own.
          </motion.p>
        </section>

        {/* PROTOCOL TRACE */}
        <section id="protocol" className="ed-section" style={{ paddingTop: 0 }}>
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Built on Kiro</p>
              <h2 className="ed-h2">One Kiro runtime. A durable identity for every job.</h2>
              <p className="ed-body ed-body-lead">
                The product starts with the official programmatic surface. KYN launches{" "}
                <code className="ed-inline-code">kiro-cli acp</code> and speaks newline-delimited
                JSON-RPC 2.0 over stdin and stdout. Kiro keeps ownership of reasoning, models, and
                tools; KYN owns the agents, queues, channels, policies, and durable outcomes
                around those sessions.
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
{`spawn `}<span className="cmd">kiro-cli acp</span>{`
  → initialize
  → session/new  `}<span className="cmt">{`{ cwd, mcpServers }`}</span>{`
  → session/set_mode      `}<span className="cmt">{`(optional)`}</span>{`
  → session/set_model     `}<span className="cmt">{`(optional)`}</span>{`
  → session/prompt        `}<span className="cmt">{`{ sessionId, prompt: [...] }`}</span>{`
  ← session/update        `}<span className="cmt">{`(text, thinking, tool_call, usage)`}</span>{`
  ← session/request_permission  `}<span className="cmt">{`(tool_call awaits your call)`}</span>{`
  → `}<span className="path">approve / reject</span>{`
  ← prompt response       `}<span className="cmt">{`{ stopReason }`}</span>
                  </code>
                </pre>
              </div>
            </Reveal>

            <Reveal delay={0.18}>
              <div className="ed-install-notes">
                <div>
                  <p className="ed-eyebrow">What the control plane guarantees</p>
                  <p className="ed-body">
                    Every accepted turn gets a durable record. Work for one agent stays ordered;
                    different agents can move concurrently. Permission requests always receive an
                    explicit answer, and a session is persisted before it is treated as recoverable.
                  </p>
                </div>
                <div>
                  <p className="ed-eyebrow">What stays with Kiro</p>
                  <p className="ed-body">
                    Model calls, context assembly, planning, tool execution, and the actual agentic
                    work. That separation means KYN can improve the product experience without
                    pretending to be a second agent harness.
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
                Implementation is only one stage. The workflow fixes the path through isolation,
                your deterministic checks, bounded repair, independent review, and a final human
                handoff. The model can reason; it cannot quietly redefine done.
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
                <code className="ed-inline-code">src/kiro_bot/</code>. Everything durable lives in a
                local SQLite database under <code className="ed-inline-code">~/.kiro-bot/</code>,
                while secrets remain environment references resolved only when a session starts.
              </p>
            </Reveal>

            <Reveal delay={0.08}>
              <div className="ed-map">
                {SUBSYSTEMS.map((subsystem) => (
                  <div key={subsystem.area} className="ed-map-row">
                    <div className="ed-map-area">
                      <span className="ed-map-title">{subsystem.area}</span>
                      <span className="ed-map-file">src/kiro_bot/{subsystem.file}</span>
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
              <p className="ed-eyebrow">Productization roadmap</p>
              <h2 className="ed-h2">What must be true before this serves a team.</h2>
              <p className="ed-body ed-body-lead">
                The local prototype is intentionally honest about its boundary. A hosted or
                organization-wide product still needs identity, tenancy, budgets, publishing, and
                richer native integrations—not merely another landing-page promise.
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
                <KiroGlyph className="glyph" size={22} />
                KYN
              </div>
              <p className="ed-footer-tag">
                An independent orchestration layer around Kiro's Agent Client Protocol. Kiro
                remains the execution engine.
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
                <li><button type="button" onClick={() => scrollTo("roadmap")}>Roadmap</button></li>
              </ul>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Safety</p>
              <ul>
                <li>Approvals answered, never dropped</li>
                <li>Secrets stay in env vars</li>
                <li>Audit is payload-free</li>
                <li>Reviewer bot can't push</li>
              </ul>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Runtime</p>
              <ul>
                <li>Loopback binding by default</li>
                <li>SQLite under ~/.kiro-bot/</li>
                <li>One controller per data dir</li>
                <li>Telegram polled, not webhooked</li>
              </ul>
            </div>
          </div>
          <div className="ed-footer-bottom">
            <span className="ed-footer-fine">
              Built independently around Kiro's ACP interface. No source files from any Kiro
              distribution are included.
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
