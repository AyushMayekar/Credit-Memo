import { AlertTriangle, Check } from "lucide-react";

const TONES = {
  MEMO_READY: "final",
  AI_READY: "complete",
  VALIDATED: "complete",
  COMPLETED: "complete",
  PREPARING_DOCUMENTS: "active",
  PREPARING_AI: "active",
  GENERATING_MEMO: "active",
  PROCESSING: "active",
  RUNNING: "active",
  WAITING_FOR_CONTENT_REVIEW: "active",
  DOCUMENTS_UPLOADED: "neutral",
  PENDING: "neutral",
  QUEUED: "neutral",
  DRAFT: "neutral",
  FAILED: "failed",
  CANCELLED: "failed",
  ERROR: "failed",
};

function humanize(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .toLowerCase();
}

export default function StatusChip({ status, className = "" }) {
  const key = String(status || "").toUpperCase();
  const tone = TONES[key] || "neutral";
  const label = humanize(status);

  return (
    <span
      className={`chip chip--${tone} ${className}`.trim()}
      title={label}
    >
      {tone === "complete" || tone === "final" ? (
        <Check size={10} aria-hidden="true" />
      ) : tone === "failed" ? (
        <AlertTriangle size={10} aria-hidden="true" />
      ) : (
        <span className="chip__dot" aria-hidden="true" />
      )}
      <span>{label}</span>
    </span>
  );
}
