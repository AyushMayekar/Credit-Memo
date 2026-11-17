import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ExternalLink,
  FileText,
  RefreshCw,
  Search,
  Upload,
} from "lucide-react";
import { useParams } from "react-router";
import { api, apiBase } from "../api/client";
import ConfirmButton from "../components/ConfirmButton";
import CreditMemoViewer from "../components/CreditMemoViewer";
import ExtractionReview from "../components/ExtractionReview";
import StageProgress from "../components/StageProgress";
import StatusChip from "../components/StatusChip";
import { useUI } from "../context/UIContext";

export default function Workspace() {
  const { ref } = useParams();
  const { toast, askConfirm, runWithLoading } = useUI();

  const [application, setApplication] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [job, setJob] = useState(null);
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState(null);
  const [memo, setMemo] = useState(null);
  const [memoId, setMemoId] = useState(null);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [loadError, setLoadError] = useState(null);

  async function load() {
    const [app, docs, memos] = await Promise.all([
      api.getApplication(ref),
      api.listDocuments(ref),
      api.listMemos(ref),
    ]);

    setApplication(app);
    setDocuments(docs);

    if (memos.length > 0) {
      const latestMemo = memos[0];
      const detail = await api.getMemo(latestMemo.memo_id);

      setMemo(detail.memo);
      setMemoId(latestMemo.memo_id);
      setPdfUrl(
        detail.pdf_available
          ? api.downloadMemoPdfUrl(latestMemo.memo_id)
          : null,
      );
    } else {
      setMemo(null);
      setMemoId(null);
      setPdfUrl(null);
    }
  }

  useEffect(() => {
    let active = true;
    setLoadError(null);
    setApplication(null);

    load().catch((error) => {
      if (active) {
        setLoadError(error.message || "The workspace could not be loaded.");
        toast(error.message, "error");
      }
    });

    return () => {
      active = false;
    };
  }, [ref]);

  useEffect(() => {
    if (!job || ["COMPLETED", "FAILED"].includes(job.status)) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      api
        .getJob(job.job_reference)
        .then((updated) => {
          setJob(updated);

          if (updated.status === "COMPLETED") {
            toast(
              updated.job_type === "AI_PREPARATION"
                ? "Documents are ready for AI"
                : "Document extraction completed",
            );

            load().catch((error) => {
              toast(error.message, "error");
            });
          }

          if (updated.status === "FAILED") {
            toast(
              updated.error_message || "Processing job failed",
              "error",
            );

            load().catch((error) => {
              toast(error.message, "error");
            });
          }
        })
        .catch((error) => {
          toast(error.message, "error");
        });
    }, 2200);

    return () => window.clearInterval(timer);
  }, [job]);

  async function upload(event) {
    const file = event.target.files[0];

    if (!file) {
      return;
    }

    const approved = await askConfirm({
      title: "Upload this document?",
      message: `${file.name} will be added to this assessment.`,
    });

    if (!approved) {
      event.target.value = "";
      return;
    }

    try {
      await runWithLoading(() => api.uploadDocument(ref, file), {
        title: "Uploading document",
        message: "Validating and securely storing the selected PDF.",
        success: "Document uploaded successfully",
      });

      await load();
    } catch {
      // Central error handling.
    } finally {
      event.target.value = "";
    }
  }

  async function startExtraction() {
    const pendingDocuments = documents.filter(
      (document) => document.status !== "COMPLETED",
    );

    const selectedDocuments =
      pendingDocuments.length > 0 ? pendingDocuments : documents;

    const result = await api.startExtraction(
      ref,
      selectedDocuments.map((document) => document.document_id),
    );

    setJob(result);
  }

  async function startAiPreparation() {
    const result = await api.startAiPreparation(ref, null);
    setJob(result);
  }

  async function askAssistant() {
    if (!query.trim()) {
      return;
    }

    const approved = await askConfirm({
      title: "Search the document evidence?",
      message: "The assistant will search already prepared evidence.",
    });

    if (!approved) {
      return;
    }

    try {
      const result = await runWithLoading(() => api.ask(ref, query), {
        title: "Searching evidence",
        message: "Finding relevant passages and preparing an answer.",
        success: "Answer ready",
      });

      setAnswer(result);
    } catch {
      // Central error handling.
    }
  }

  async function generateMemo() {
    const result = await api.generateMemo(ref);

    setMemo(result.memo);
    setMemoId(result.memo_id);
    setPdfUrl(null);

    await load();
  }

  async function exportPdf() {
    if (!memoId) {
      toast("Generate or load a credit memo before exporting.", "error");
      return;
    }

    const approved = await askConfirm({
      title: "Export this credit memo as PDF?",
      message: "A PDF will be generated from the structured memo.",
    });

    if (!approved) {
      return;
    }

    try {
      await runWithLoading(() => api.exportMemoPdf(memoId), {
        title: "Generating PDF",
        message: "Rendering the credit memo.",
        success: "Credit memo PDF is ready",
      });

      setPdfUrl(api.downloadMemoPdfUrl(memoId));
    } catch {
      // Central error handling.
    }
  }

  function retry() {
    setLoadError(null);
    setApplication(null);
    load().catch((error) => {
      setLoadError(error.message || "The workspace could not be loaded.");
    });
  }

  if (loadError) {
    return (
      <div className="state state--error state--page">
        <AlertTriangle size={22} aria-hidden="true" />
        <div>
          <h3>Workspace could not be loaded</h3>
          <p>{loadError}</p>
        </div>
        <button type="button" className="btn btn--secondary" onClick={retry}>
          <RefreshCw size={15} aria-hidden="true" />
          Retry
        </button>
      </div>
    );
  }

  if (!application) {
    return (
      <div className="stack" aria-busy="true" aria-label="Loading workspace">
        <span className="skeleton skeleton--banner" />
        <span className="skeleton skeleton--panel" />
        <div className="workspace-layout">
          <span className="skeleton skeleton--panel" />
          <span className="skeleton skeleton--panel" />
        </div>
      </div>
    );
  }

  const aiReady = ["AI_READY", "MEMO_READY"].includes(application.status);
  const memoReady = application.status === "MEMO_READY";
  const extractionReady =
    application.status === "WAITING_FOR_CONTENT_REVIEW" &&
    documents.length > 0 &&
    documents.every((document) => document.status === "COMPLETED");
  const extractionValidated =
    documents.length > 0 &&
    documents.every((document) => document.status === "VALIDATED");
  const canStartExtraction =
    documents.length > 0 &&
    ["DOCUMENTS_UPLOADED", "FAILED"].includes(application.status);
  const canPrepareAi = extractionValidated && !aiReady;

  const amount = Number(application.loan_amount);
  const formattedAmount = Number.isFinite(amount)
    ? amount.toLocaleString()
    : application.loan_amount;

  const totalPages = documents.reduce(
    (sum, document) => sum + (Number(document.page_count) || 0),
    0,
  );

  return (
    <div className="stack">
      <section className="identity" aria-labelledby="application-title">
        <div className="identity__main">
          <div className="identity__top">
            <span className="mono">{application.application_reference}</span>
            <StatusChip status={application.status} />
          </div>
          <h2 id="application-title">{application.borrower_name}</h2>
          <p className="identity__purpose">{application.loan_purpose}</p>
        </div>

        <div className="identity__amount">
          <span className="identity__label">Requested facility</span>
          <strong>
            {application.currency} {formattedAmount}
          </strong>
          <span className="identity__tenure">
            {application.tenure_months} months
          </span>
        </div>
      </section>

      <StageProgress
        application={application}
        documents={documents}
        job={job}
      />

      <div className="workspace-layout">
        <div className="workspace-main stack">
          <section className="panel" aria-labelledby="documents-title">
            <div className="panel__head">
              <div>
                <p className="eyebrow">Documents</p>
                <h2 id="documents-title">Source documents</h2>
                <p className="panel__description">
                  PDFs used for direct text and table extraction.
                </p>
              </div>

              <label className="btn btn--secondary upload-button">
                <Upload size={15} aria-hidden="true" />
                Add PDF
                <input
                  className="sr-only"
                  type="file"
                  accept="application/pdf"
                  onChange={upload}
                />
              </label>
            </div>

            {!documents.length ? (
              <div className="empty empty--compact">
                <FileText size={20} aria-hidden="true" />
                <h3>No documents uploaded</h3>
                <p>Add one or more PDFs to begin extraction.</p>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="data-table data-table--documents">
                  <thead>
                    <tr>
                      <th scope="col">Document</th>
                      <th scope="col">Status</th>
                      <th scope="col">Pages</th>
                      <th scope="col" className="ta-right">
                        Open
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((document) => (
                      <tr key={document.document_id}>
                        <td>
                          <span className="document-name">
                            <FileText size={15} aria-hidden="true" />
                            {document.filename}
                          </span>
                        </td>
                        <td>
                          <StatusChip status={document.status} />
                        </td>
                        <td className="muted">
                          {document.page_count || "—"}
                        </td>
                        <td className="ta-right">
                          <a
                            className="btn btn--ghost btn--icon"
                            href={`${apiBase}/documents/${document.document_id}/file`}
                            target="_blank"
                            rel="noreferrer"
                            aria-label={`Open ${document.filename}`}
                          >
                            <ExternalLink size={14} aria-hidden="true" />
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {canStartExtraction && (
              <div className="panel__foot">
                <div>
                  <strong>
                    {application.status === "FAILED"
                      ? "Retry document extraction"
                      : "Start document extraction"}
                  </strong>
                  <p>
                    Selectable text and tables will be extracted from all{" "}
                    {documents.length} document
                    {documents.length === 1 ? "" : "s"}.
                  </p>
                </div>
                <ConfirmButton
                  title={
                    application.status === "FAILED"
                      ? "Retry document extraction?"
                      : "Start document extraction?"
                  }
                  message={`Selectable text and tables will be extracted from all ${documents.length} document(s).`}
                  onConfirm={startExtraction}
                  success="Extraction job started"
                  loadingTitle="Starting extraction"
                  loadingMessage="Only selectable text and tables will be extracted."
                >
                  {application.status === "FAILED"
                    ? "Retry extraction"
                    : "Start extraction"}
                </ConfirmButton>
              </div>
            )}
          </section>

          {extractionReady && (
            <ExtractionReview
              reference={ref}
              documents={documents}
              onApproved={load}
            />
          )}

          {canPrepareAi && (
            <section className="panel" aria-labelledby="ai-prep-title">
              <div className="panel__head">
                <div>
                  <p className="eyebrow">Extraction approved</p>
                  <h2 id="ai-prep-title">Prepare evidence for AI</h2>
                  <p className="panel__description">
                    Structural parsing, optimized chunking, batched
                    embeddings and FAISS indexing will run using the
                    approved extraction.
                  </p>
                </div>
              </div>
              <div className="panel__foot panel__foot--end">
                <ConfirmButton
                  title="Prepare these documents for AI?"
                  message="The validated extraction will be parsed, chunked, embedded and indexed."
                  onConfirm={startAiPreparation}
                  success="AI preparation job started"
                  loadingTitle="Starting AI preparation"
                  loadingMessage="Preparing the background parsing and indexing job."
                >
                  Prepare documents for AI
                </ConfirmButton>
              </div>
            </section>
          )}

          {aiReady && (
            <section className="panel" aria-labelledby="ask-title">
              <div className="panel__head">
                <div>
                  <p className="eyebrow">Ask AI</p>
                  <h2 id="ask-title">Explore existing evidence</h2>
                  <p className="panel__description">
                    Ask about financial performance, risks, or governance.
                  </p>
                </div>
              </div>

              <div className="panel__body">
                <form
                  className="ask"
                  onSubmit={(event) => {
                    event.preventDefault();
                    askAssistant();
                  }}
                >
                  <span className="ask__icon" aria-hidden="true">
                    <Search size={16} />
                  </span>
                  <input
                    className="input ask__input"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Ask about financial performance, risks, or governance"
                    aria-label="Ask about the prepared evidence"
                  />
                  <button
                    type="submit"
                    className="btn btn--primary"
                    disabled={!query.trim()}
                  >
                    Ask
                  </button>
                </form>

                {answer && (
                  <article className="answer">
                    <div className="answer__head">
                      <span className="eyebrow">Answer</span>
                      {answer.route && (
                        <span className="mono">{answer.route}</span>
                      )}
                    </div>
                    <p>{answer.response?.answer}</p>

                    {!!answer.sources?.length && (
                      <div className="source-list">
                        <span className="source-list__label">Sources</span>
                        {answer.sources.map((source) => (
                          <span
                            className="source-chip"
                            key={source.source_id}
                          >
                            {source.source_reference}
                          </span>
                        ))}
                      </div>
                    )}
                  </article>
                )}
              </div>
            </section>
          )}
        </div>

        <aside className="workspace-rail" aria-label="Assessment details">
          <section className="panel">
            <div className="panel__head panel__head--compact">
              <div>
                <p className="eyebrow">Assessment</p>
                <h2>Details</h2>
              </div>
            </div>
            <dl className="facts">
              <div>
                <dt>Reference</dt>
                <dd className="mono">
                  {application.application_reference}
                </dd>
              </div>
              <div>
                <dt>Currency</dt>
                <dd>{application.currency}</dd>
              </div>
              <div>
                <dt>Tenure</dt>
                <dd>{application.tenure_months} months</dd>
              </div>
              <div>
                <dt>Documents</dt>
                <dd>{documents.length}</dd>
              </div>
              <div>
                <dt>Pages</dt>
                <dd>{totalPages || "—"}</dd>
              </div>
              <div>
                <dt>Memo</dt>
                <dd>{memoReady ? `Version ${memo?.report_metadata?.memo_version ?? "—"}` : "Not generated"}</dd>
              </div>
            </dl>
          </section>
        </aside>
      </div>

      {aiReady && (
        <section className="panel" aria-labelledby="memo-title">
          <div className="panel__head">
            <div>
              <p className="eyebrow">Credit memo</p>
              <h2 id="memo-title">
                {memoReady
                  ? "Review or create a new version"
                  : "Create an evidence-backed draft"}
              </h2>
              <p className="panel__description">
                Structured sections generated from the indexed evidence.
              </p>
            </div>

            <ConfirmButton
              title={
                memoReady
                  ? "Create a new memo version?"
                  : "Generate credit memo?"
              }
              message="The system will create a structured draft from existing indexed evidence."
              onConfirm={generateMemo}
              success="Credit memo draft is ready"
              loadingTitle="Building the credit memo"
              loadingMessage="Generating and validating memo sections."
            >
              {memoReady ? (
                <>
                  <RefreshCw size={15} aria-hidden="true" />
                  Create new version
                </>
              ) : (
                "Generate memo"
              )}
            </ConfirmButton>
          </div>

          {memo && memoId ? (
            <div className="panel__body panel__body--tight">
              <CreditMemoViewer
                memo={memo}
                memoId={memoId}
                onExport={exportPdf}
                pdfUrl={pdfUrl}
                previewUrl={api.previewMemoUrl(memoId)}
              />
            </div>
          ) : (
            <div className="panel__body">
              <p className="empty-note">
                No credit memo has been generated for this assessment yet.
              </p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
