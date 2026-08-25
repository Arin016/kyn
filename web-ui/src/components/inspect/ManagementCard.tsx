import type { ReactNode } from "react";
import { Badge } from "../ui/Basics";

export interface ManagementCardData {
  title: string;
  meta?: string;
  badge?: string;
  badgeTone?: "accent" | "success" | "warning" | "danger" | "muted";
  enabled?: boolean;
  actions?: ReactNode;
}

export function ManagementCard({ title, meta, badge, badgeTone, enabled = true, actions }: ManagementCardData) {
  return (
    <article className="management-card">
      <div className="management-card-top">
        <div className="management-title">{title}</div>
        {badge && (
          <Badge tone={badgeTone ?? (enabled ? "success" : "muted")} dot>
            {badge}
          </Badge>
        )}
      </div>
      {meta && <div className="management-meta">{meta}</div>}
      {actions && <div className="management-actions">{actions}</div>}
    </article>
  );
}

export function ActionLink({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button type="button" className="danger-link" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}
