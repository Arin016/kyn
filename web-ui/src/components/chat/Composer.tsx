import { useEffect, useMemo, useRef, useState } from "react";
import type { SlashCommand, SlashChoice } from "../../lib/slash";

interface Props {
  disabled: boolean;
  busy: boolean;
  hint: string;
  mirrorNote: boolean;
  placeholder: string;
  onSubmit: (message: string) => void;
  onStop: () => void;
  /** Present → the composer speaks slash commands. */
  commands?: SlashCommand[];
  /** Present → typing `@` opens member autocomplete. */
  members?: string[];
  /** External draft (turn Edit action): applied + focused on change. */
  draft?: { text: string; nonce: number } | null;
}

interface SlashState {
  open: boolean;
  /** Command whose choice list is showing; null → top level. */
  active: SlashCommand | null;
  choices: SlashChoice[];
  loading: boolean;
  /** Filter text while a choice list is open (everything after the command). */
  query: string;
  highlight: number;
}

const NO_SLASH: SlashState = { open: false, active: null, choices: [], loading: false, query: "", highlight: 0 };

export function Composer({
  disabled,
  busy,
  hint,
  mirrorNote,
  placeholder,
  onSubmit,
  onStop,
  commands,
  members,
  draft,
}: Props) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const [value, setValue] = useState("");
  const [slash, setSlash] = useState<SlashState>(NO_SLASH);
  const [mentions, setMentions] = useState<{ open: boolean; query: string; highlight: number }>({
    open: false,
    query: "",
    highlight: 0,
  });

  const resize = () => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 190)}px`;
  };

  useEffect(() => {
    resize();
  }, []);

  // External draft (turn Edit action): fill, refocus, and let the operator
  // review before sending — rerun stays a conscious act, not a blind replay.
  useEffect(() => {
    if (!draft) return;
    const node = inputRef.current;
    if (node) node.value = draft.text;
    setValue(draft.text);
    resize();
    node?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.nonce]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && busy) onStop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onStop]);

  const hasSlash = Boolean(commands && commands.length > 0);
  const closeSlash = () => setSlash(NO_SLASH);
  const clearInput = () => {
    if (inputRef.current) inputRef.current.value = "";
    setValue("");
    resize();
  };

  /** Everything after the command word — the choice-list filter. */
  const choiceQuery = (text: string) => {
    const at = text.indexOf(" ");
    return at === -1 ? "" : text.slice(at + 1).trim();
  };

  /** Commands (top level) or choices (inside a command), filtered by what's typed. */
  const filteredCommands = useMemo(() => {
    if (slash.active) return [];
    const term = value.replace(/^\/+/, "").trim().toLowerCase();
    return (commands || []).filter(
      (command) =>
        !term ||
        command.id.startsWith(term) ||
        (command.keywords || []).some((word) => word.startsWith(term)),
    );
  }, [value, slash.active, commands]);

  const filteredChoices = useMemo(() => {
    if (!slash.active) return [];
    const term = slash.query.toLowerCase();
    return slash.choices.filter(
      (choice) => !term || choice.label.toLowerCase().includes(term) || choice.id.includes(term),
    );
  }, [slash]);

  const mentionMatches = useMemo(() => {
    if (!mentions.open) return [];
    const query = mentions.query.toLowerCase();
    return (members || []).filter((name) => !query || name.toLowerCase().includes(query)).slice(0, 6);
  }, [mentions, members]);

  /** Run a command with no choice list; open one otherwise. */
  const openCommand = (command: SlashCommand) => {
    if (!command.choices) {
      command.run(undefined);
      closeSlash();
      clearInput();
      return;
    }
    const resolved = typeof command.choices === "function" ? command.choices() : command.choices;
    if (resolved instanceof Promise) {
      setSlash({ open: true, active: command, choices: [], loading: true, query: choiceQuery(value), highlight: 0 });
      void resolved.then((choices) => {
        setSlash((current) =>
          current.active === command ? { ...current, choices, loading: false, highlight: 0 } : current,
        );
      });
    } else {
      setSlash({ open: true, active: command, choices: resolved, loading: false, query: choiceQuery(value), highlight: 0 });
    }
  };

  const pickChoice = (choice: SlashChoice) => {
    slash.active?.run(choice);
    closeSlash();
    clearInput();
  };

  const updateFromInput = () => {
    const next = inputRef.current?.value || "";
    setValue(next);
    resize();

    // Mention autocomplete — an @token at the end of the text.
    if (members && members.length > 0) {
      const match = next.match(/(?:^|\s)@([A-Za-z0-9_\-.]*)$/);
      if (match) {
        setMentions({ open: true, query: match[1], highlight: 0 });
      } else if (mentions.open) {
        setMentions((current) => ({ ...current, open: false }));
      }
    }

    // Slash menu — "/" opens it, editing the filter updates it.
    if (hasSlash && next.startsWith("/")) {
      setSlash((current) =>
        current.active
          ? { ...current, open: true, query: choiceQuery(next) }
          : { ...NO_SLASH, open: true },
      );
    } else if (slash.open) {
      closeSlash();
    }
  };

  const applyMention = (name: string) => {
    const node = inputRef.current;
    if (!node) return;
    node.value = node.value.replace(/@([A-Za-z0-9_\-.]*)$/, `@${name} `);
    setValue(node.value);
    setMentions({ open: false, query: "", highlight: 0 });
    node.focus();
    resize();
  };

  const submit = () => {
    const text = inputRef.current?.value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    clearInput();
    closeSlash();
    setMentions({ open: false, query: "", highlight: 0 });
  };

  const onComposerKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentions.open && mentionMatches.length > 0) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setMentions((current) => ({
          ...current,
          highlight:
            (current.highlight + (event.key === "ArrowDown" ? 1 : mentionMatches.length - 1)) %
            mentionMatches.length,
        }));
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        applyMention(mentionMatches[mentions.highlight] || mentionMatches[0]);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setMentions((current) => ({ ...current, open: false }));
        return;
      }
    }

    if (!slash.open) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submit();
      }
      return;
    }

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const count = Math.max(slash.active ? filteredChoices.length : filteredCommands.length, 1);
      setSlash((current) => ({
        ...current,
        highlight: (current.highlight + (event.key === "ArrowDown" ? 1 : count - 1)) % count,
      }));
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      if (slash.active) {
        const choice = filteredChoices[slash.highlight];
        if (choice) pickChoice(choice);
      } else {
        const command = filteredCommands[slash.highlight];
        if (command) openCommand(command);
      }
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      if (slash.active) {
        // Back out to the top level, leaving the command typed.
        const id = slash.active.id;
        setSlash({ ...NO_SLASH, open: true });
        if (inputRef.current) inputRef.current.value = `/${id} `;
        setValue(`/${id} `);
      } else {
        closeSlash();
      }
    }
  };

  return (
    <div className="composer-zone">
      {mirrorNote && <p className="remote-note">Reply from your phone. This view is a live mirror of the remote thread.</p>}
      <div className="composer-anchor">
        {slash.open && (
          <div className="slash-menu" id="kyn-slash-menu" role="listbox" aria-label="Commands">
            {!slash.active ? (
              <>
                <p className="slash-head">Commands</p>
                {filteredCommands.length === 0 && (
                  <p className="slash-note">No command matches “{value}”.</p>
                )}
                {filteredCommands.map((command, index) => (
                  <button
                    key={command.id}
                    type="button"
                    role="option"
                    aria-selected={index === slash.highlight}
                    className={`slash-row${index === slash.highlight ? " is-active" : ""}`}
                    onMouseEnter={() => setSlash((current) => ({ ...current, highlight: index }))}
                    onClick={() => openCommand(command)}
                  >
                    <span className="slash-cmd">/{command.id}</span>
                    <span className="slash-name">{command.name}</span>
                    <span className="slash-hint">{command.hint}</span>
                  </button>
                ))}
              </>
            ) : (
              <>
                <p className="slash-head">
                  <button
                    type="button"
                    className="slash-back"
                    onClick={() => {
                      const id = slash.active?.id || "";
                      setSlash({ ...NO_SLASH, open: true });
                      if (inputRef.current) inputRef.current.value = `/${id} `;
                      setValue(`/${id} `);
                      inputRef.current?.focus();
                    }}
                  >
                    ← /{slash.active?.id}
                  </button>
                  <span>{slash.active?.name}</span>
                </p>
                {slash.loading && <p className="slash-note">Loading…</p>}
                {!slash.loading && filteredChoices.length === 0 && <p className="slash-note">Nothing matches.</p>}
                {filteredChoices.map((choice, index) => (
                  <button
                    key={choice.id}
                    type="button"
                    role="option"
                    aria-selected={index === slash.highlight}
                    disabled={choice.disabled}
                    className={`slash-row${index === slash.highlight ? " is-active" : ""}`}
                    onMouseEnter={() => setSlash((current) => ({ ...current, highlight: index }))}
                    onClick={() => pickChoice(choice)}
                  >
                    <span className="slash-name">{choice.label}</span>
                    {choice.detail && <span className="slash-hint">{choice.detail}</span>}
                  </button>
                ))}
              </>
            )}
          </div>
        )}

        {mentions.open && mentionMatches.length > 0 && (
          <div className="mention-menu" role="listbox" aria-label="Mention a bot">
            {mentionMatches.map((name, index) => (
              <button
                key={name}
                type="button"
                role="option"
                aria-selected={index === mentions.highlight}
                className={`slash-row${index === mentions.highlight ? " is-active" : ""}`}
                onMouseEnter={() => setMentions((current) => ({ ...current, highlight: index }))}
                onClick={() => applyMention(name)}
              >
                <span className="slash-name">@{name}</span>
                <span className="slash-hint">Only {name} acts on this</span>
              </button>
            ))}
          </div>
        )}

        <form
          ref={formRef}
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
          className="composer-shell"
        >
          <textarea
            ref={inputRef}
            className="composer-textarea"
            rows={1}
            placeholder={placeholder}
            disabled={disabled}
            aria-label="Message your bot"
            autoComplete="off"
            onInput={updateFromInput}
            onKeyDown={onComposerKeyDown}
          />
          <div className="composer-footer">
            <span className="composer-hint">{hint}</span>
            {busy ? (
              <>
                <button
                  type="submit"
                  className="send-btn queue-mode"
                  disabled={disabled}
                  aria-label="Queue message behind the current run"
                  title="Queue message behind the current run"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
                    <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
                <button
                  type="button"
                  className="send-btn stop-mode"
                  onClick={onStop}
                  aria-label="Stop generating (Esc)"
                  title="Stop generating (Esc)"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                    <rect x="6" y="6" width="12" height="12" rx="2" />
                  </svg>
                </button>
              </>
            ) : (
              <button type="submit" className="send-btn" disabled={disabled} aria-label="Send">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
                  <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
