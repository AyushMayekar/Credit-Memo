import {
  ExternalLink,
  FileText,
  RefreshCw,
  Search,
  Sparkles,
  Upload,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router";

import { api, apiBase } from "../api/client";
import ConfirmButton from "../components/ConfirmButton";
import CreditMemoViewer from "../components/CreditMemoViewer";
import ExtractionReview from "../components/ExtractionReview";
import StageProgress from "../components/StageProgress";
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
    load().catch((error) => toast(error.message, "error"));
  }, [ref]);

  useEffect(() => {
    if (!job || ["COMPLETED", "FAILED"].includes(job.status)) {
      return;
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
      pendingDocuments.length > 0
        ? pendingDocuments
        : documents;

    const result = await api.startExtraction(
      ref,
      selectedDocuments.map(
        (document) => document.document_id,
      ),
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
      message:
        "The assistant will search already prepared evidence.",
    });

    if (!approved) {
      return;
    }

    try {
      const result = await runWithLoading(
        () => api.ask(ref, query),
        {
          title: "Searching evidence",
          message:
            "Finding relevant passages and preparing an answer.",
          success: "Answer ready",
        },
      );

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
      toast(
        "Generate or load a credit memo before exporting.",
        "error",
      );
      return;
    }

    const approved = await askConfirm({
      title: "Export this credit memo as PDF?",
      message:
        "A PDF will be generated from the structured memo.",
    });

    if (!approved) {
      return;
    }

    try {
      await runWithLoading(
        () => api.exportMemoPdf(memoId),
        {
          title: "Generating PDF",
          message: "Rendering the credit memo.",
          success: "Credit memo PDF is ready",
        },
      );

      setPdfUrl(api.downloadMemoPdfUrl(memoId));
    } catch {
      // Central error handling.
    }
  }

  if (!application) {
    return (
      <div className="empty clay">
        Loading application workspace…
      </div>
    );
  }

  const aiReady = ["AI_READY", "MEMO_READY"].includes(
    application.status,
  );

  const memoReady = application.status === "MEMO_READY";

  const extractionReady =
    application.status === "WAITING_FOR_CONTENT_REVIEW" &&
    documents.length > 0 &&
    documents.every(
      (document) => document.status === "COMPLETED",
    );

  const extractionValidated =
    documents.length > 0 &&
    documents.every(
      (document) => document.status === "VALIDATED",
    );

  const canStartExtraction =
    documents.length > 0 &&
    ["DOCUMENTS_UPLOADED", "FAILED"].includes(
      application.status,
    );

  return (
    <div className="workspace">
      <section className="clay summary">
        <div>
          <p className="eyebrow">
            {application.application_reference}
          </p>

          <h2>{application.borrower_name}</h2>

          <p className="summary-meta">
            <strong>
              {application.currency}{" "}
              {Number(
                application.loan_amount,
              ).toLocaleString()}
            </strong>

            <span />

            {application.loan_purpose}
          </p>
        </div>

        <span
          className={`status status-${application.status.toLowerCase()}`}
        >
          {application.status.replaceAll("_", " ")}
        </span>
      </section>

      {job && <StageProgress job={job} />}

      <section className="clay panel compact-panel">
        <div className="section-title">
          <div>
            <p className="eyebrow">Documents</p>
            <h2>Source documents</h2>

            <p className="muted">
              PDFs used for direct text and table extraction.
            </p>
          </div>

          <label className="button secondary upload-button">
            <Upload size={17} />
            Add PDF

            <input
              hidden
              type="file"
              accept="application/pdf"
              onChange={upload}
            />
          </label>
        </div>

        <div className="document-list">
          {documents.map((document) => (
            <article
              className="document-row"
              key={document.document_id}
            >
              <span className="document-icon">
                <FileText />
              </span>

              <div className="document-main">
                <strong>{document.filename}</strong>

                <span
                  className={`mini-status mini-${document.status.toLowerCase()}`}
                >
                  {document.status.replaceAll("_", " ")}
                </span>
              </div>

              <span className="page-count">
                {document.page_count || "–"} pages
              </span>

              <a
                className="icon-button"
                href={`${apiBase}/documents/${document.document_id}/file`}
                target="_blank"
                rel="noreferrer"
                aria-label="Open PDF"
              >
                <ExternalLink />
              </a>
            </article>
          ))}
        </div>

        {canStartExtraction && (
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
        )}
      </section>

      {extractionReady && (
        <ExtractionReview
          reference={ref}
          documents={documents}
          onApproved={load}
        />
      )}

      {extractionValidated && !aiReady && (
        <section className="clay panel">
          <p className="eyebrow">Extraction approved</p>

          <h2>Prepare validated evidence for AI</h2>

          <p className="muted">
            Structural parsing, optimized chunking, batched
            embeddings and FAISS indexing will run using the
            approved extraction.
          </p>

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
        </section>
      )}

      {aiReady && (
        <>
          <section className="clay panel compact-panel">
            <div className="section-title compact">
              <div>
                <p className="eyebrow">Ask AI</p>
                <h2>Explore existing evidence</h2>
              </div>
            </div>

            <div className="ask-row">
              <Search className="input-icon" />

              <input
                value={query}
                onChange={(event) =>
                  setQuery(event.target.value)
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    askAssistant();
                  }
                }}
                placeholder="Ask about financial performance, risks, or governance"
              />

              <button
                type="button"
                className="button primary"
                onClick={askAssistant}
                disabled={!query.trim()}
              >
                Ask
              </button>
            </div>

            {answer && (
              <article className="answer-card">
                <span className="answer-icon">
                  <Sparkles />
                </span>

                <div>
                  <p>{answer.response?.answer}</p>

                  {!!answer.sources?.length && (
                    <div className="source-list">
                      {answer.sources.map((source) => (
                        <span key={source.source_id}>
                          {source.source_reference}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </article>
            )}
          </section>

          <section className="clay panel compact-panel">
            <div className="section-title">
              <div>
                <p className="eyebrow">Credit memo</p>

                <h2>
                  {memoReady
                    ? "Review or create a new version"
                    : "Create an evidence-backed draft"}
                </h2>
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
                    <RefreshCw size={17} />
                    Create new version
                  </>
                ) : (
                  "Generate memo"
                )}
              </ConfirmButton>
            </div>

            {memo && memoId && (
              <CreditMemoViewer
                memo={memo}
                memoId={memoId}
                onExport={exportPdf}
                pdfUrl={pdfUrl}
                previewUrl={api.previewMemoUrl(memoId)}
              />
            )}
          </section>
        </>
      )}
    </div>
  );
}