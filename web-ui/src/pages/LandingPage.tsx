import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { KiroGlyph } from "../components/KiroGlyph";

type Persona = {
  role: string;
  outcome: string;
  body: string;
  detail: string;
};

const PERSONAS: Persona[] = [
  {
    role: "The Builder",
    outcome: "Ships a fix. Waits for you to merge.",
    body:
      "Point it at a task and a repo. It writes into a detached Git worktree, runs the checks you gave, and retries on failure until the bounded repair limit. Your checkout never moves. Nothing pushes.",
    detail: "Detached worktree · bounded repair · artifact manifest",
  },
  {
    role: "The Reviewer",
    outcome: "Reads every diff before you do.",
    body:
      "A different Kiro with its own policy. It reads the artifact manifest, not the writer's plan. If it edits anything, the SHA-256 changes and the mutation is flagged. Approval stays a keystroke only you can send.",
    detail: "Independent bot · mutation detection · human handoff",
  },
  {
    role: "The Foreman",
    outcome: "Named in your channels. Answers on the same thread.",
    body:
      "Bind it to Slack, GitHub, WhatsApp, email, or Telegram. Signatures are verified against the raw body. Delivery IDs deduplicate. Telegram is polled from your laptop, so no public URL is needed.",
    detail: "Six signed sources · thread isolation · no public URL for Telegram",
  },
  {
    role: "The Watcher",
    outcome: "Runs on the schedule you keep.",
    body:
      "Give it a prompt and a cadence — every hour, every Monday, or a specific timestamp. It survives crashes with lease-based recovery and never runs the same routine twice. It's the teammate that reads the dashboards while you sleep.",
    detail: "Interval or one-shot · lease-based recovery · no double-fire",
  },
  {
    role: "The Planner",
    outcome: "Sends the whole team as a plan.",
    body:
      "Draft a graph of named bots with real dependencies. Independent branches run in parallel. Failures propagate up. Cancellation cascades down. The plan itself is the durable artifact — reload the page, the plan is still there.",
    detail: "DAG execution · bounded fan-out · cascade cancel",
  },
];

const WHATS_NEW = [
  {
    label: "New",
    title: "Verified coding lifecycle",
    body: "Builder → your checks → repair → reviewer → your keystroke. Mutation detection built in.",
  },
  {
    label: "Ships now",
    title: "Six signed channels",
    body: "Slack, GitHub, WhatsApp, email, generic webhook, and Telegram — polled, no public URL.",
  },
  {
    label: "Ships now",
    title: "Multi-bot delegation",
    body: "Named bots as a DAG. Bounded fan-out, cascade cancel, durable across restarts.",
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
            <button type="button" onClick={() => scrollTo("roster")}>Roster</button>
            <button type="button" onClick={onOpenEngineering}>How it works</button>
            <button type="button" onClick={onOpenEngineering}>Engineering</button>
            <button type="button" className="ed-btn ed-btn-primary" onClick={onEnterConsole}>
              Open the console
            </button>
          </nav>
        </div>
      </header>

      <main id="main">
        {/* HERO — two-column, Kiro-style */}
        <section className="ed-container ed-hero-2col">
          <div className="ed-hero">
            <motion.p
              className="ed-eyebrow"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
            >
              A team of Kiros
            </motion.p>
            <motion.h1
              className="ed-hero-h1"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.06, ease: [0.22, 1, 0.36, 1] }}
            >
              Kiros for every job you'd
              <br />
              <span className="ed-accent-word">hand a teammate.</span>
            </motion.h1>
            <motion.p
              className="ed-lead"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.14 }}
            >
              Named Kiros, each with its own memory, workspace, and boundaries. Delegate the way
              you'd delegate to a person. Nothing merges without your keystroke.
            </motion.p>
            <motion.div
              className="ed-cta-row"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.22 }}
            >
              <button type="button" className="ed-btn ed-btn-primary" onClick={onEnterConsole}>
                Open the console
              </button>
              <button type="button" className="ed-btn ed-btn-secondary" onClick={() => scrollTo("roster")}>
                Meet the roster ↓
              </button>
            </motion.div>
          </div>

          <motion.aside
            className="ed-hero-side"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            aria-label="What ships now"
          >
            <p className="ed-eyebrow">What ships now</p>
            <ul>
              {WHATS_NEW.map((item) => (
                <li key={item.title}>
                  <span className="ed-side-label">{item.label}</span>
                  <p className="ed-side-title">{item.title}</p>
                  <p className="ed-side-body">{item.body}</p>
                </li>
              ))}
            </ul>
          </motion.aside>
        </section>

        {/* ROSTER */}
        <section id="roster" className="ed-section" style={{ paddingTop: 0 }}>
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">The roster</p>
              <h2 className="ed-h2">Five Kiros. Five specialties.</h2>
              <p className="ed-body ed-body-lead">
                Each is a real bot in the console, with its own memory, its own approval policy,
                and its own boundary. Name them what you want. Give them the jobs you'd otherwise
                do yourself.
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
              <p className="ed-eyebrow">The stance</p>
              <h2 className="ed-h2">
                The point of a control plane is that some of the buttons don't exist.
              </h2>
              <p className="ed-body" style={{ marginTop: "1.75rem", fontSize: "1.125rem" }}>
                We could have written a sixth Kiro that pushes code and opens pull requests. We
                didn't. The reviewer is a different Kiro. The artifact is hashed. The handoff is a
                request only you can send. If your product's edge is shipping code faster than a
                human can read it, ours is the opposite bet.
              </p>
              <button
                type="button"
                className="ed-textlink"
                onClick={onOpenEngineering}
                style={{ marginTop: "2rem" }}
              >
                How we make that safe <span className="arrow">→</span>
              </button>
            </Reveal>
          </div>
        </section>

        {/* INSTALL */}
        <section className="ed-section">
          <div className="ed-container">
            <Reveal>
              <p className="ed-eyebrow">Get it running</p>
              <h2 className="ed-h2">Three commands. Loopback only.</h2>
              <p className="ed-body ed-body-lead">
                Kiro Bot is a single Python daemon. It binds to 127.0.0.1 until you put it behind
                the auth of your choice.
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
                  <p className="ed-eyebrow">Then</p>
                  <p className="ed-body">
                    Open the console. Name your Builder. Name your Reviewer. Bind Slack, GitHub,
                    or Telegram if you want them reachable from your phone.
                  </p>
                </div>
                <div>
                  <p className="ed-eyebrow">Wanted next</p>
                  <p className="ed-body">
                    Auth, org boundaries, and a publisher that opens pull requests. Reviewer-driven
                    push. Bot-to-bot mailboxes.{" "}
                    <button
                      type="button"
                      className="ed-inline-link ed-inline-button"
                      onClick={onOpenEngineering}
                    >
                      What we haven't built yet
                    </button>
                    .
                  </p>
                </div>
              </div>
            </Reveal>
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
                An independent orchestration layer around Kiro's Agent Client Protocol. Kiro
                remains the execution engine.
              </p>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Product</p>
              <ul>
                <li><button type="button" onClick={onEnterConsole}>Console</button></li>
                <li><button type="button" onClick={() => scrollTo("roster")}>The roster</button></li>
                <li><button type="button" onClick={onOpenEngineering}>How it works</button></li>
              </ul>
            </div>
            <div className="ed-footer-col">
              <p className="ed-eyebrow">Roles</p>
              <ul>
                <li>Builder</li>
                <li>Reviewer</li>
                <li>Foreman</li>
                <li>Watcher</li>
                <li>Planner</li>
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
