import type { MemoryRecord } from "../../types";
import { fullTime, truncate } from "../../lib/format";
import { ManagementCard } from "./ManagementCard";
import { EmptyState } from "../ui/Basics";

interface Props {
  records: MemoryRecord[];
}

export function MemoryTab({ records }: Props) {
  return (
    <>
      <div className="panel-action-row">
        <p>Durable evidence shared across the local chat and authenticated external threads.</p>
      </div>
      <div className="management-list">
        {records.length === 0 && <EmptyState>No shared memories yet.</EmptyState>}
        {records.slice(0, 30).map((record, index) => (
          <ManagementCard
            key={index}
            title={truncate(record.request_text || "Recorded exchange", 62)}
            meta={`${truncate(record.response_text || "No textual response", 150)}\n${fullTime(record.created_at)}`}
            badge={String(record.scope || "unknown").replace(/^channel:/, "")}
            enabled
          />
        ))}
      </div>
    </>
  );
}
