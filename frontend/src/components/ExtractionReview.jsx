import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useUI } from "../context/UIContext";

export default function ExtractionReview({ reference, documents, onApproved }) {
  const { toast, askConfirm } = useUI();
  const [documentId, setDocumentId] = useState(documents[0]?.document_id || null);
  const [data, setData] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!documentId) return;
    setData(null); setPageNumber(1);
    api.getDocumentExtraction(documentId).then(setData).catch((error) => toast(error.message, "error"));
  }, [documentId]);

  const page = data?.pages?.find((item) => item.page_number === pageNumber);

  async function approve() {
    const approved = await askConfirm({
      title: "Approve this extraction?",
      message: "Confirm that the extracted text and tables match the original PDFs. After approval, you can start AI preparation.",
    });
    if (!approved) return;
    setBusy(true);
    try {
      const result = await api.approveExtractions(reference);
      toast(result.message || "Extraction approved");
      await onApproved();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="clay panel">
      <div className="section-title">
        <div><p className="eyebrow">Extraction validation</p><h2>Review extracted text and tables</h2><p className="muted">Compare this output with the original PDF before AI preparation.</p></div>
        <button type="button" className="button primary" onClick={approve} disabled={busy || !data}>{busy ? "Approving…" : "Approve extraction"}</button>
      </div>
      <div className="tabs">{documents.map((document) => <button key={document.document_id} type="button" className={documentId === document.document_id ? "active" : ""} onClick={() => setDocumentId(document.document_id)}>{document.filename}</button>)}</div>
      {data && <>
        <div className="extraction-pager"><button type="button" className="button secondary" disabled={pageNumber <= 1} onClick={() => setPageNumber((value) => value - 1)}>Previous</button><strong className="extraction-page-label">Page {pageNumber} of {data.document.page_count}</strong><button type="button" className="button secondary" disabled={pageNumber >= data.document.page_count} onClick={() => setPageNumber((value) => value + 1)}>Next</button></div>
        <div className="memo-subsection"><h3>Extracted text</h3><pre style={{ whiteSpace: "pre-wrap", maxHeight: 500, overflow: "auto" }}>{page?.text || "No selectable text extracted."}</pre></div>
        <div className="memo-subsection"><h3>Extracted tables</h3>{!page?.tables?.length && <p className="muted">No tables detected on this page.</p>}{page?.tables?.map((table) => <div key={table.table_id} style={{ overflowX: "auto", marginBottom: 18 }}><strong>{table.table_id}</strong><table className="metric-table"><tbody>{table.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>)}</div>
        {!!page?.warnings?.length && <div className="box quality"><strong>Warnings</strong><ul>{page.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
      </>}
    </section>
  );
}
