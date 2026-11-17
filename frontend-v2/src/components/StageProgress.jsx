import { AlertTriangle } from "lucide-react";
import StatusChip from "./StatusChip";

function buildSteps(application, documents) {
  const hasDocuments = documents.length > 0;
  const validated =
    hasDocuments &&
    documents.every((document) => document.status === "VALIDATED");
  const aiReady = ["AI_READY", "MEMO_READY"].includes(application.status);
  const memoReady = application.status === "MEMO_READY";

  const complete = [hasDocuments, validated, aiReady, memoReady];

  const details = [
    hasDocuments
      ? `${documents.length} document${documents.length === 1 ? "" : "s"}`
      : "Upload source PDFs",
    validated
      ? "Extraction approved"
      : hasDocuments
        ? "Review extracted content"
        : "Awaiting documents",
    aiReady
      ? "Evidence indexed"
      : validated
        ? "Prepare for search"
        : "Awaiting approval",
    memoReady
      ? "Draft available"
      : aiReady
        ? "Generate the memo"
        : "Awaiting evidence",
  ];

  const failed = application.status === "FAILED";
  let currentMarked = false;

  return ["Documents", "Review", "AI evidence", "Credit memo"].map(
    (label, index) => {
      let state = "todo";

      if (complete[index]) {
        state = "done";
      } else if (!currentMarked) {
        state = failed ? "failed" : "current";
        currentMarked = true;
      }

      return { label, detail: details[index], state };
    },
  );
}

export default function StageProgress({ application, documents, job }) {
  const steps = buildSteps(application, documents);
  const progress = Math.max(
    0,
    Math.min(100, Number(job?.progress_percentage) || 0),
  );

  return (
    <section className="panel progress-panel" aria-labelledby="progress-title">
      <div className="panel__head progress-panel__head">
        <div>
          <p className="eyebrow">Workflow</p>
          <h2 id="progress-title">Assessment progress</h2>
        </div>
        {job && <StatusChip status={job.status} />}
      </div>

      <div className="panel__body">
        <ol className="pipeline">
          {steps.map((step, index) => (
            <li
              className={`pipeline__step pipeline__step--${step.state}`}
              key={step.label}
            >
              <span className="pipeline__num" aria-hidden="true">
                {step.state === "failed" ? (
                  <AlertTriangle size={12} />
                ) : (
                  index + 1
                )}
              </span>
              <span className="pipeline__text">
                <span className="pipeline__label">{step.label}</span>
                <span className="pipeline__detail">{step.detail}</span>
              </span>
            </li>
          ))}
        </ol>

        {job && (
          <div className="job">
            <div className="job__row">
              <div className="job__meta">
                <strong>
                  {job.current_stage_label ||
                    job.current_stage ||
                    "Processing"}
                </strong>
                <span className="muted">
                  {job.error_message ||
                    job.message ||
                    "Your request is queued."}
                </span>
              </div>
              <span className="job__value">{progress}%</span>
            </div>

            <div
              className="progress"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress}
              aria-label="Job progress"
            >
              <span style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
