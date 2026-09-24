import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AriGlyph } from "../components/AriGlyph";

type Persona = {
  role: string;
  outcome: string;
  body: string;
  detail: string;
};

const PERSONAS: Persona[] = [
  {
    role: "Builder",
    outcome: "Turns a repo task into reviewable work.",
    body:
      "Give a builder a repository, a clear outcome, and the checks that matter. Ari keeps the task on its own branch, runs the checks, and brings the diff back for review.",
    detail: "Isolated branch · real checks · inspect the diff",
  },
  {
    role: "Reviewer",
    outcome: "Adds a second agent before you decide.",
    body:
      "Choose another bot to inspect the change with fresh context. Read its findings and the diff, then decide whether the task is ready to merge into your base branch.",
    detail: "Independent review · visible findings · your call",
  },
  {
    role: "Triage",
    outcome: "Picks up work from the conversations you use.",
    body:
      "Route Slack mentions, GitHub issues, WhatsApp messages, Telegram chats, signed email events, or webhooks to the bot that owns the next step.",
    detail: "Slack · GitHub · WhatsApp · Telegram · email · webhooks",
  },
  {
    role: "Operator",
    outcome: "Keeps recurring work on a schedule.",
    body:
      "Turn a dependable instruction into a one-time or repeating routine. See its runs, status, and next action in the same place as approvals and active work.",
    detail: "One-time or recurring · durable run history",
  },
  {
    role: "Coordinator",
    outcome: "Passes a useful brief between different agents.",
    body:
      "Hand work between Kiro, OpenCode, and Codex with the goal, recent conversation, and repository evidence attached. Or build a multi-bot plan and follow each result as it comes back.",
    detail: "Cross-engine handoff · team plans · inspectable results",
  },
];

const PRODUCT_PROMISES = [
  {
    label: "One workspace",
    title: "Keep your agent tools together",
    body: "Create bots for Kiro, OpenCode, and Codex, then pick the right one for the work.",
  },
  {
    label: "One work inbox",
    title: "See what needs your attention",
    body: "Bring approvals, coding tasks, agent runs, workflows, and channel events into one review queue.",
  },
  {
    label: "Human-led",
    title: "Keep the important decisions yours",
    body: "Review tool approvals, task diffs, handoffs, and plugin access as work moves forward.",
  },
];

const PRODUCT_PILLARS = [
  {
    eyebrow: "Choose the right engine",
    title: "Kiro, OpenCode, and Codex in one crew.",
    body:
      "Give each bot its own engine, model settings, tools, workspace, and purpose. Continue with the same bot or hand the work to another engine with a portable brief.",
  },
  {
    eyebrow: "See the whole picture",
    title: "Your work, gathered in one inbox.",
    body:
      "Find pending approvals, coding tasks, agent runs, workflows, and incoming channel events without hunting through separate panels. Jump straight to the decision or review that is waiting.",
  },
  {
    eyebrow: "Make changes reviewable",
    title: "Give coding work a branch and a finish line.",
    body:
      "A task runs in an isolated worktree, executes the checks you define, and gets an independent review. Inspect its files and diff before approving the handoff and merging it to your base branch.",
  },
  {
    eyebrow: "Connect what you need",
    title: "Browse integrations, then choose what each bot can use.",
    body:
      "Explore the plugin catalogue, configure MCP connections, and bind them to selected bots. Ari asks for approval according to each bot’s policy when a tool needs permission.",
  },
];

const FAQS = [
  {
    question: "Which agent engines can I use?",
    answer:
      "Create bots with Kiro, OpenCode, or Codex. The installed engine handles model reasoning and tool execution; Ari gives bots one workspace for conversations, work, integrations, and review. Each engine keeps its own sign-in and account.",
  },
  {
    question: "Is Ari another coding model?",
    answer:
      "No. Ari is the workspace around your coding agents. It helps you organize bots, route work, connect tools, carry a task between engines, and review important actions.",
  },
  {
    question: "Does Ari keep working when my laptop is closed?",
    answer:
      "When Ari is running on your Mac, keep it online for scheduled work and incoming channels. Reach it from another device through a private Tailscale connection. You can also host Ari remotely, with the deployment security configured by you.",
  },
  {
    question: "Can Ari make coding changes?",
    answer:
      "Ari can run a coding task on its own branch, execute your checks, and ask a separate bot to review it. You inspect the result and approve before Ari merges the reviewed task into its base branch. Ari does not open pull requests or publish changes for you.",
  },
  {
    question: "Where does my data live?",
    answer:
      "In the macOS setup, Ari stores its workspace data locally under ~/.ari. Engine credentials stay with the engine you installed. Plugin secrets are supplied through environment variables, and Ari's audit log records decisions without raw tool payloads.",
  },
];

function Reveal({
  children,
  delay = 0,
}: {
  children: React.ReactNode;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.15 }}
      transition={{ duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

function PersonaCard({ persona, index }: { persona: Persona; index: number }) {
  return (
    <Reveal delay={index * 0.05}>
      <article className="ed-persona">
        <div className="ed-persona-head">
          <span className="ed-persona-role">{persona.role}</span>
          <span className="ed-persona-idx">{String(index + 1).padStart(2, "0")}</span>
        </div>
        <h3 className="ed-persona-outcome">{persona.outcome}</h3>
        <p className="ed-persona-body">{persona.body}</p>
        <span className="ed-persona-detail">{persona.detail}</span>
      </article>
    </Reveal>
  );
}

interface Props {
  onEnterConsole: () => void;
  onOpenEngineering: () => void;
  onTryDemo: () => void;
}

export default function LandingPage({ onEnterConsole, onOpenEngineering, onTryDemo }: Props) {
  const [scrolled, setScrolled] = useState(false);

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
            onClick={() => {
              document.querySelector(".ed")?.scrollTo({ top: 0, behavior: "smooth" });
            }}
            aria-label="Ari — home"
          >
            <AriGlyph className="glyph" size={26} tone="ink" />
            Ari
          </button>
          <nav className="ed-nav-links" aria-label="Primary">
            <button type="button" onClick={() => scrollTo("why")}>Why Ari</button>
            <button type="button" onClick={() => scrollTo("roster")}>Jobs</button>
            <button type="button" onClick={onOpenEngineering}>How Ari works</button>
            <button type="button" className="ed-btn ed-btn-primary" onClick={onEnterConsole}>
              Start with a bot
            </button>
          </nav>
        </div>
      </header>

      <main id="main">
        {/* HERO — paper canvas, ink mark watermark */}
        <section className="ed-hero-stage">
          <div className="ed-hero-canvas" aria-hidden="true">
            <AriGlyph className="ed-hero-mark" size={560} tone="ink" />
            <div className="ed-hero-vignette" />
          </div>
          <div className="ed-container ed-hero-2col">
          <div className="ed-hero">
            <motion.p
              className="ed-eyebrow"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
            >
              Your AI crew, ready to work
            </motion.p>
            <motion.h1
              className="ed-hero-h1"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.06, ease: [0.22, 1, 0.36, 1] }}
            >
              Your agents.
              <br />
              <span className="ed-accent-word">One steady crew.</span>
            </motion.h1>
            <motion.p
              className="ed-lead"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.14 }}
            >
              Bring Kiro, OpenCode, and Codex into one thoughtful workspace. Route work to the
              right bot, keep tasks and approvals in view, and carry a useful handoff wherever the
              next step belongs.
            </motion.p>
            <motion.div
              className="ed-cta-row"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.22 }}
            >
              <button type="button" className="ed-btn ed-btn-primary" onClick={onEnterConsole}>
                Open Ari
              </button>
              <button type="button" className="ed-btn ed-btn-secondary" onClick={() => scrollTo("roster")}>
                Explore the workspace ↓
              </button>
              <button type="button" className="ed-btn ed-btn-secondary" onClick={onTryDemo}>
                See a live product demo →
              </button>
            </motion.div>
            <motion.div
              className="ed-hero-strip"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.3 }}
            >
              {["Kiro · OpenCode · Codex", "work inbox", "reviewable tasks", "MCP plugins", "handoffs"].map(
                (item) => (
                  <span className="ed-hero-chip" key={item}>
                    {item}
                  </span>
                ),
              )}
            </motion.div>
          </div>

          <motion.aside
            className="ed-hero-side"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            aria-label="Built for real work"
          >
            <p className="ed-eyebrow">Built for real work</p>
            <ul>
              {PRODUCT_PROMISES.map((item) => (
                <li key={item.title}>
                  <span className="ed-side-label">{item.label}</span>
                  <p className="ed-side-title">{item.title}</p>
                  <p className="ed-side-body">{item.body}</p>
                </li>
              ))}
            </ul>
          </motion.aside>
          </div>
        </section>

        {/* WHY */}
        <section id="why" className="ed-section" style={{ paddingTop: 0 }}>
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Why Ari</p>
              <h2 className="ed-h2">The agent is only part of the work.</h2>
              <p className="ed-body ed-body-lead">
                Real work moves between people, projects, tools, and days. Ari gives your agents a
                shared place to pick up context, carry work forward, and bring decisions back to you.
              </p>
            </Reveal>
            <div className="ed-scenes">
              {PRODUCT_PILLARS.map((pillar, index) => (
                <Reveal key={pillar.title} delay={index * 0.05}>
                  <article className="ed-scene">
                    <span className="ed-scene-eyebrow">{pillar.eyebrow}</span>
                    <h3 className="ed-scene-title">{pillar.title}</h3>
                    <p className="ed-scene-body">{pillar.body}</p>
                  </article>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ROSTER */}
        <section id="roster" className="ed-section" style={{ paddingTop: 0 }}>
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Ways to work with Ari</p>
              <h2 className="ed-h2">Give each bot a job worth returning to.</h2>
              <p className="ed-body ed-body-lead">
                Set up a builder, reviewer, operator, or coordinator around a real responsibility.
                Choose the engine and tools that fit, then add another bot when the work calls for it.
              </p>
            </Reveal>

            <div className="ed-roster">
              {PERSONAS.slice(0, 3).map((persona, index) => (
                <PersonaCard key={persona.role} persona={persona} index={index} />
              ))}
            </div>
            <div className="ed-roster ed-roster-two">
              {PERSONAS.slice(3).map((persona, index) => (
                <PersonaCard key={persona.role} persona={persona} index={index + 3} />
              ))}
            </div>
          </div>
        </section>

        {/* MANIFESTO */}
        <section className="ed-band">
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Ari's role</p>
              <h2 className="ed-h2">
                Your engines do the work. Ari keeps it moving.
              </h2>
              <p className="ed-body" style={{ marginTop: "1.75rem", fontSize: "1.125rem" }}>
                Kiro, OpenCode, and Codex remain the reasoning and tool-use engines. Ari adds the
                layer around them: named bots, shared context, a work inbox, schedules, channels,
                workflows, MCP integrations, isolated coding tasks, and reviewable handoffs.
              </p>
              <button
                type="button"
                className="ed-textlink"
                onClick={onOpenEngineering}
                style={{ marginTop: "2rem" }}
              >
                See the system under the surface <span className="arrow">→</span>
              </button>
            </Reveal>
          </div>
        </section>

        {/* INSTALL */}
        <section id="start-local" className="ed-section">
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Start with your crew</p>
              <h2 className="ed-h2">Choose the agents you already work with.</h2>
              <p className="ed-body ed-body-lead">
                Run Ari locally on your Mac and connect Kiro, OpenCode, or Codex from setup. Your
                engine sign-in stays with its own CLI; Ari brings their work into one control room.
              </p>
            </Reveal>

            <Reveal delay={0.1}>
              <div className="ed-install">
                <div className="ed-install-head">
                  <span className="dots" aria-hidden>
                    <span /><span /><span />
                  </span>
                  <span className="ed-install-path">~/your-project</span>
                  <span className="ed-install-label">zsh</span>
                </div>
                <pre>
                  <code>
{`$ `}<span className="cmd">uv sync</span>{` --extra server --extra dev
$ `}<span className="cmd">uv run ari bot create</span>{` builder --cwd `}<span className="path">~/your-project</span>{` --engine opencode
$ `}<span className="cmd">uv run ari serve</span>{`   `}<span className="cmt">{`# http://127.0.0.1:8765`}</span>
                  </code>
                </pre>
              </div>
            </Reveal>

            <Reveal delay={0.18}>
              <div className="ed-install-notes">
                <div>
                  <p className="ed-eyebrow">Start with one job</p>
                  <p className="ed-body">
                    Choose an engine, set the project folder, and describe the result you need.
                    Keep tool access and approvals aligned with the bot's job.
                  </p>
                </div>
                <div>
                  <p className="ed-eyebrow">Then grow the roster</p>
                  <p className="ed-body">
                    Add another engine, connect the channel where work arrives, install an MCP
                    integration, or turn a reliable prompt into a routine.{" "}
                    <button
                      type="button"
                      className="ed-inline-link ed-inline-button"
                      onClick={onOpenEngineering}
                    >
                      Explore how Ari works
                    </button>
                    .
                  </p>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="ed-band">
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Questions worth asking</p>
              <h2 className="ed-h2">A workspace with clear edges.</h2>
            </Reveal>
            <div className="ed-faq">
              {FAQS.map((item) => (
                <details key={item.question} className="ed-faq-item">
                  <summary>{item.question}</summary>
                  <p>{item.answer}</p>
                </details>
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
                One workspace for Kiro, OpenCode, Codex, and the work they take on.
              </p>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Product</p>
              <ul>
                <li><button type="button" onClick={onEnterConsole}>Console</button></li>
                <li><button type="button" onClick={() => scrollTo("why")}>Why Ari</button></li>
                <li><button type="button" onClick={() => scrollTo("roster")}>Jobs</button></li>
                <li><button type="button" onClick={onOpenEngineering}>How it works</button></li>
              </ul>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Roles</p>
              <ul>
                <li>Builder</li>
                <li>Reviewer</li>
                <li>Triage Agent</li>
                <li>Operator</li>
                <li>Coordinator</li>
              </ul>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Safety</p>
              <ul>
                <li>Approvals answered, never dropped</li>
                <li>Secrets stay in env vars</li>
                <li>Audit is payload-free</li>
                <li>Reviewed tasks merge only after approval</li>
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
