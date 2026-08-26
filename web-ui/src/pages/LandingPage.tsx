import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { KiroGlyph } from "../components/KiroGlyph";
import { PixelKiro } from "../components/PixelKiro";

type Persona = {
  role: string;
  outcome: string;
  body: string;
  detail: string;
};

const PERSONAS: Persona[] = [
  {
    role: "The Builder",
    outcome: "Takes an issue to a reviewed handoff.",
    body:
      "Give it the outcome and the repo. It works in an isolated checkout, runs your real checks, repairs what fails, and brings back a change another agent has reviewed. Your working tree never moves.",
    detail: "Build → verify → repair → independent review",
  },
  {
    role: "The Reviewer",
    outcome: "Gives every change a clean second look.",
    body:
      "A separate Kiro inspects the result with fresh context and its own policy. If the reviewer changes the work, Kiro Bot catches it. The final handoff still belongs to you.",
    detail: "Separate context · mutation detection · human decision",
  },
  {
    role: "The Triage Agent",
    outcome: "Meets new work where it arrives.",
    body:
      "Mention it in Slack, open a GitHub issue, send a WhatsApp message, or text it on Telegram. It keeps each source thread separate and replies where the conversation started.",
    detail: "Browser · Slack · GitHub · WhatsApp · email · Telegram",
  },
  {
    role: "The Operator",
    outcome: "Owns the checks that should not depend on memory.",
    body:
      "Give one agent the recurring job: watch a queue, prepare a digest, or inspect a repo on a cadence. Kiro Bot remembers what is due and recovers accepted work after a restart.",
    detail: "One-time or repeating · durable schedule · visible history",
  },
  {
    role: "The Coordinator",
    outcome: "Moves one outcome through several specialists.",
    body:
      "Describe the outcome in chat or compose it on the visual canvas. Drag bot nodes, connect their ports with arrows, and let independent agents run in parallel while dependent work waits for the right result.",
    detail: "Conversational launch · node-and-arrow DAG · bot calls",
  },
];

const PRODUCT_PROMISES = [
  {
    label: "Persistent",
    title: "The work keeps its context",
    body: "Each named agent carries its Kiro session, history, and relevant memory into the next conversation.",
  },
  {
    label: "Reachable",
    title: "Talk from where the work happens",
    body: "Use the browser, Slack, GitHub, WhatsApp, email, a signed webhook, or Telegram.",
  },
  {
    label: "Governed",
    title: "Autonomy with a hard edge",
    body: "Policies, quotas, per-action approvals, isolated workspaces, and an audit trail stay outside the model.",
  },
];

const PRODUCT_PILLARS = [
  {
    eyebrow: "Keep the thread",
    title: "One prompt ends. The job does not have to.",
    body:
      "Kiro Bot gives every agent a durable identity and conversation. Come back tomorrow, switch from browser to phone, or resume after a restart without rebuilding the working context from zero.",
  },
  {
    eyebrow: "Run a roster",
    title: "Use one agent per responsibility.",
    body:
      "Keep implementation, review, triage, and operations in separate hands. Each agent gets its own queue, policy, memory, and Kiro session—and several can work at once.",
  },
  {
    eyebrow: "Bring the work to you",
    title: "Message the same agent from your desk or phone.",
    body:
      "A GitHub issue, Slack thread, WhatsApp message, email event, or Telegram chat can reach the agent that owns the job. Replies return to the originating thread.",
  },
  {
    eyebrow: "Trust the harness",
    title: "The model proposes. The control plane decides.",
    body:
      "Tool policy, quotas, reload-safe approval routing, workspace isolation, deterministic checks, and final handoffs are enforced by code. Every gate is one decision—never blanket trust.",
  },
];

const FAQS = [
  {
    question: "Can one bot actually launch work on other bots?",
    answer:
      "Yes. A governed built-in control tool can create, inspect, start, and cancel durable team workflows from the conversation. It can also call a different named bot for one focused result. The same graph can be composed visually in Workflow Studio with draggable bot nodes, ports, arrows, zoom, and automatic layout.",
  },
  {
    question: "Is Kiro Bot another coding model?",
    answer:
      "No. Kiro remains the agentic engine that reasons, writes code, and uses tools. Kiro Bot is the independent local control plane that adds durable agents, channels, schedules, coordination, governance, and verified work around Kiro's ACP interface.",
  },
  {
    question: "Does it keep working when my laptop is closed?",
    answer:
      "Not in the current local-first build. The daemon and Kiro CLI run on a machine you control, so that machine must remain online for background routines and remote channels. A remote deployment is possible, but authentication and network hardening are your responsibility today.",
  },
  {
    question: "Can Kiro Bot merge or publish code for me?",
    answer:
      "Not today. The verified coding lifecycle stops at a human-approved handoff after isolated implementation, deterministic checks, bounded repair, and independent review. It does not push, open a pull request, merge, or publish on its own.",
  },
  {
    question: "Where does my data live?",
    answer:
      "Bot state is stored locally in SQLite under ~/.kiro-bot by default. Secrets remain environment-variable references, and the audit ledger records decisions without storing raw tool payloads.",
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
}

export default function LandingPage({ onEnterConsole, onOpenEngineering }: Props) {
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
            aria-label="Kiro Bot — home"
          >
            <KiroGlyph className="glyph" size={26} />
            Kiro Bot
          </button>
          <nav className="ed-nav-links" aria-label="Primary">
            <button type="button" onClick={() => scrollTo("why")}>Why Kiro Bot</button>
            <button type="button" onClick={() => scrollTo("roster")}>Jobs</button>
            <button type="button" onClick={onOpenEngineering}>Engineering</button>
            <button type="button" className="ed-btn ed-btn-primary" onClick={onEnterConsole}>
              Start with a bot
            </button>
          </nav>
        </div>
      </header>

      <main id="main">
        {/* HERO — two-column, Kiro-style */}
        <section className="ed-hero-stage">
          <PixelKiro />
          <div className="ed-hero-vignette" aria-hidden="true" />
          <div className="ed-container ed-hero-2col">
          <div className="ed-hero">
            <motion.p
              className="ed-eyebrow"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
            >
              Persistent agents for Kiro
            </motion.p>
            <motion.h1
              className="ed-hero-h1"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.06, ease: [0.22, 1, 0.36, 1] }}
            >
              Put Kiro to work
              <br />
              <span className="ed-accent-word">beyond the terminal.</span>
            </motion.h1>
            <motion.p
              className="ed-lead"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.14 }}
            >
              Create named agents with clear jobs, durable context, and hard boundaries. Reach
              them from your browser or phone, run several at once, and stay in control of the
              decisions that matter.
            </motion.p>
            <motion.div
              className="ed-cta-row"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.22 }}
            >
              <button type="button" className="ed-btn ed-btn-primary" onClick={onEnterConsole}>
                Meet your first bot
              </button>
              <button type="button" className="ed-btn ed-btn-secondary" onClick={() => scrollTo("roster")}>
                See what it can do ↓
              </button>
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
              <p className="ed-eyebrow">Why Kiro Bot</p>
              <h2 className="ed-h2">The agent is only half the product.</h2>
              <p className="ed-body ed-body-lead">
                Real work lasts longer than a prompt. It crosses repos, channels, reviews, and
                days. Kiro Bot supplies the durable system around Kiro so you are not the queue,
                scheduler, memory, and approval router yourself.
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
              <p className="ed-eyebrow">Jobs to hand off</p>
              <h2 className="ed-h2">Build the roster your work needs.</h2>
              <p className="ed-body ed-body-lead">
                Start with one durable responsibility, not a generic helper. Add another agent
                when the work needs a different context, policy, schedule, or point of view.
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
              <p className="ed-eyebrow">The division of work</p>
              <h2 className="ed-h2">
                Kiro does the work. Kiro Bot keeps it moving.
              </h2>
              <p className="ed-body" style={{ marginTop: "1.75rem", fontSize: "1.125rem" }}>
                Kiro remains the reasoning and tool-use engine. Kiro Bot adds the operating layer
                around it: identity, memory, queues, schedules, channels, coordination, isolated
                workspaces, approvals, and evidence. It is built for work that should survive the
                chat window without surrendering the final decision.
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
        <section className="ed-section">
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Start local</p>
              <h2 className="ed-h2">Your first agent is three commands away.</h2>
              <p className="ed-body ed-body-lead">
                Kiro Bot runs against the Kiro CLI you already use and binds to your machine by
                default. Create a named agent, open the control room, and hand it a real job.
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
$ `}<span className="cmd">uv run kiro-bot bot create</span>{` builder --cwd `}<span className="path">~/your-project</span>{`
$ `}<span className="cmd">uv run kiro-bot serve</span>{`   `}<span className="cmt">{`# http://127.0.0.1:8765`}</span>
                  </code>
                </pre>
              </div>
            </Reveal>

            <Reveal delay={0.18}>
              <div className="ed-install-notes">
                <div>
                  <p className="ed-eyebrow">Start with one job</p>
                  <p className="ed-body">
                    Define the outcome, the repo, and what must come back to you for approval. Let
                    the agent complete one useful task before adding schedules or more roles.
                  </p>
                </div>
                <div>
                  <p className="ed-eyebrow">Then grow the roster</p>
                  <p className="ed-body">
                    Add a reviewer, connect the channel where work arrives, or turn a reliable
                    prompt into a routine.{" "}
                    <button
                      type="button"
                      className="ed-inline-link ed-inline-button"
                      onClick={onOpenEngineering}
                    >
                      See the honest roadmap
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
              <h2 className="ed-h2">Know what runs. Know where it stops.</h2>
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
                <KiroGlyph className="glyph" size={22} />
                Kiro Bot
              </div>
              <p className="ed-footer-tag">
                The local control plane for persistent Kiro agents, recurring work, and governed
                coding handoffs.
              </p>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Product</p>
              <ul>
                <li><button type="button" onClick={onEnterConsole}>Console</button></li>
                <li><button type="button" onClick={() => scrollTo("why")}>Why Kiro Bot</button></li>
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
