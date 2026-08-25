import { memo, useMemo, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div
      style={{
        margin: "0.8em 0",
        borderRadius: "var(--r-code)",
        border: "1px solid var(--border-strong)",
        overflow: "hidden",
        background: "var(--code-bg)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "6px 12px",
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-raised)",
        }}
      >
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", color: "var(--fg-faint)" }}>
          {language || "text"}
        </span>
        <button
          type="button"
          onClick={() => void copy()}
          aria-label={copied ? "Copied" : "Copy code"}
          style={{
            appearance: "none",
            border: "none",
            background: "transparent",
            color: copied ? "var(--success)" : "var(--fg-muted)",
            fontSize: "0.72rem",
            fontWeight: 600,
            cursor: "pointer",
            padding: "2px 8px",
            borderRadius: 6,
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre
        style={{
          margin: 0,
          padding: "12px 14px",
          overflowX: "auto",
          fontFamily: "var(--font-mono)",
          fontSize: "0.82rem",
          lineHeight: 1.65,
          color: "var(--fg-secondary)",
        }}
      >
        <code>{code}</code>
      </pre>
    </div>
  );
}

/**
 * One stable markdown block. Memoized so streaming only re-parses the tail.
 */
const MarkdownBlock = memo(function MarkdownBlock({ text }: { text: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noreferrer noopener">
            {children}
          </a>
        ),
        pre: ({ children }) => <>{children}</>,
        code: ({ className, children }) => {
          const raw = String(children ?? "");
          const match = /language-(\w+)/.exec(className || "");
          const isBlock = raw.includes("\n") || Boolean(match);
          if (isBlock) return <CodeBlock code={raw.replace(/\n$/, "")} language={match?.[1]} />;
          return <code>{children}</code>;
        },
      }}
    >
      {text}
    </Markdown>
  );
});

/**
 * Split streaming prose into stable blocks (double-newline separated) and
 * parse each independently. Only the last block re-renders per token.
 */
export const StableProse = memo(function StableProse({
  text,
  streaming = false,
}: {
  text: string;
  streaming?: boolean;
}) {
  const blocks = useMemo(() => text.split(/\n{2,}/), [text]);
  return (
    <>
      {blocks.map((block, index) => (
        <div key={index}>
          <MarkdownBlock text={block} />
          {streaming && index === blocks.length - 1 && block.length > 0 ? null : null}
        </div>
      ))}
      {streaming && <span className="streaming-caret" aria-hidden="true" />}
    </>
  );
});
