import type { ReactNode } from "react";
import { motion } from "framer-motion";

export function Badge({
  tone = "muted",
  dot = false,
  children,
}: {
  tone?: "accent" | "success" | "warning" | "danger" | "muted";
  dot?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`badge badge-${tone}`}>
      {dot && <span className="badge-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function Card({ children }: { children: ReactNode }) {
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
      className="mgmt-card"
    >
      {children}
    </motion.article>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="activity-empty">{children}</p>;
}

export function Skeleton() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="skeleton skeleton-line" />
      <div className="skeleton skeleton-line" style={{ width: "72%" }} />
      <div className="skeleton skeleton-line" style={{ width: "48%" }} />
    </div>
  );
}
