import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Loader2,
  ScrollText,
  Table2,
} from "lucide-react";
import { api } from "../api/client";
import { useUI } from "../context/UIContext";

export default function ExtractionReview({
  reference,
  documents,
  onApproved,
}) {
  const { toast, askConfirm } = useUI();
  const [documentId, setDocumentId] = useState(
    documents[0]?.document_id || null,
  );
  const [data, setData] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!documents.some((document) => document.document_id === documentId)) {
      setDocumentId(documents[0]?.document_id || null);
    }
  }, [documents, documentId]);

  useEffect(() => {
    if (!documentId) return undefined;

    let active = true;
    setData(null);
    setError(null);
    setLoading(true);
    setPageNumber(1);

    api
      .getDocumentExtraction(documentId)
      .then((result) => {
        if (active) setData(result);
      })
      .catch((failure) => {
        if (active) {
          setError(failure.message || "Extraction could not be loaded.");
          toast(failure.message, "error");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [documentId]);

  const page = data?.pages?.find(
    (item) => item.page_number === pageNumber,
  );
  const pageCount = data?.document?.page_count || 0;

  async function approve() {
    const approved = await askConfirm({
      title: "Approve this extraction?",
      message:
        "Confirm that the extracted text and tables match the original PDFs. After approval, you can start AI preparation.",
    });
    if (!approved) return;

    setBusy(true);
    try {
      const result = await api.approveExtractions(reference);
      toast(result.message || "Extraction approved");
      await onApproved();
    } catch (failure) {
      toast(failure.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="extraction-title">
      <div className="panel__head">
        <div>
          <p className="eyebrow">Validation</p>
          <h2 id="extraction-title">Extraction review</h2>
          <p className="panel__description">
            Compare extracted text and tables with the original PDF before
            AI preparation.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--primary"
          onClick={approve}
          disabled={busy || !data || loading}
        >
          {busy ? (
            <>
              <Loader2 size={15} className="spin" aria-hidden="true" />
              Approving…
            </>
          ) : (
            "Approve extraction"
          )}
        </button>
      </div>

      <div className="tabs" role="tablist" aria-label="Documents">
        {documents.map((document) => (
          <button
            key={document.document_id}
            type="button"
            role="tab"
            aria-selected={documentId === document.document_id}
            className={`tab ${
              documentId === document.document_id ? "is-active" : ""
            }`.trim()}
            onClick={() => setDocumentId(document.document_id)}
          >
            {document.filename}
          </button>
        ))}
      </div>

      <div className="panel__body panel__body--tight">
        {loading && (
          <div className="split" aria-label="Loading extraction">
            <div className="pane">
              <div className="pane__head">
                <span className="skeleton skeleton--short" />
              </div>
              <div className="pane__body">
                <span className="skeleton skeleton--block" />
                <span className="skeleton skeleton--block" />
                <span className="skeleton skeleton--block" />
              </div>
            </div>
            <div className="pane">
              <div className="pane__head">
                <span className="skeleton skeleton--short" />
              </div>
              <div className="pane__body">
                <span className="skeleton skeleton--block" />
              </div>
            </div>
          </div>
        )}

        {!loading && error && (
          <div className="state state--error" role="alert">
            <AlertTriangle size={20} aria-hidden="true" />
            <div>
              <h3>Extraction could not be loaded</h3>
              <p>{error}</p>
            </div>
          </div>
        )}

        {!loading && !error && data && (
          <div className="stack stack--sm">
            <div className="extraction-bar">
              <div className="pager">
                <button
                  type="button"
                  className="btn btn--secondary btn--sm"
                  disabled={pageNumber <= 1}
                  onClick={() =>
                    setPageNumber((value) => Math.max(1, value - 1))
                  }
                >
                  <ChevronLeft size={14} aria-hidden="true" />
                  Previous
                </button>
                <span className="pager__label mono">
                  Page {pageNumber} of {pageCount || "—"}
                </span>
                <button
                  type="button"
                  className="btn btn--secondary btn--sm"
                  disabled={!pageCount || pageNumber >= pageCount}
                  onClick={() =>
                    setPageNumber((value) =>
                      Math.min(pageCount, value + 1),
                    )
                  }
                >
                  Next
                  <ChevronRight size={14} aria-hidden="true" />
                </button>
              </div>
            </div>

            {!!page?.warnings?.length && (
              <div className="notice" role="status">
                <AlertTriangle size={15} aria-hidden="true" />
                <div>
                  <strong>Warnings on this page</strong>
                  <ul>
                    {page.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            <div className="split">
              <div className="pane">
                <div className="pane__head">
                  <span className="pane__title">
                    <ScrollText size={14} aria-hidden="true" />
                    Extracted text
                  </span>
                </div>
                <pre className="text-pane">
                  {page?.text || "No selectable text extracted."}
                </pre>
              </div>

              <div className="pane">
                <div className="pane__head">
                  <span className="pane__title">
                    <Table2 size={14} aria-hidden="true" />
                    Extracted tables
                  </span>
                </div>
                <div className="pane__body pane__body--scroll">
                  {!page?.tables?.length && (
                    <p className="muted">
                      No tables detected on this page.
                    </p>
                  )}

                  {page?.tables?.map((table, index) => (
                    <div className="table-block" key={table.table_id || index}>
                      <div className="table-block__head">
                        <span className="mono">
                          {table.table_id || `Table ${index + 1}`}
                        </span>
                        <span className="muted">
                          {table.rows?.length || 0} rows
                        </span>
                      </div>
                      <div className="table-wrap">
                        <table className="extraction-table">
                          <caption className="sr-only">
                            {table.table_id || `Table ${index + 1}`}
                          </caption>
                          <tbody>
                            {(table.rows || []).map((row, rowIndex) => (
                              <tr key={rowIndex}>
                                {row.map((cell, cellIndex) => (
                                  <td key={cellIndex}>{cell}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
