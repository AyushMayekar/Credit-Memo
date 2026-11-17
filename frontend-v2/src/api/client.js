const BASE =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, options);

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail || body);
    } catch {
      // Keep the default HTTP message.
    }
    throw new Error(message);
  }

  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json")
    ? response.json()
    : response;
}

export const api = {
  createApplication: (body) =>
    request("/applications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getApplication: (ref) => request(`/applications/${ref}`),
  listApplications: () => request("/applications"),
  uploadDocument: (ref, file) => {
    const body = new FormData();
    body.append("file", file);
    return request(`/applications/${ref}/documents`, {
      method: "POST",
      body,
    });
  },
  listDocuments: (ref) => request(`/applications/${ref}/documents`),
  startExtraction: (ref, documentIds) =>
    request(`/applications/${ref}/preparation-jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_ids: documentIds,
        reporting_year: null,
      }),
    }),
  startAiPreparation: (ref, reportingYear = null) =>
    request(`/applications/${ref}/ai-preparation-jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        process_text: true,
        process_selected_tables: true,
        process_selected_visuals: false,
        reporting_year: reportingYear,
      }),
    }),
  getJob: (id) => request(`/jobs/${id}`),
  getDocumentExtraction: (id) =>
    request(`/documents/${id}/extraction`),
  approveExtractions: (ref) =>
    request(`/applications/${ref}/extractions/approve`, {
      method: "POST",
    }),
  ask: (ref, query) =>
    request(`/applications/${ref}/ai/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    }),
  listMemos: (ref) => request(`/applications/${ref}/credit-memos`),
  getMemo: (id) => request(`/credit-memos/${id}`),
  generateMemo: (ref) =>
    request(`/applications/${ref}/credit-memos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template: "UNIVERSAL_CREDIT_MEMO_V2" }),
    }),
  previewMemoUrl: (id) => `${BASE}/credit-memos/${id}/preview`,
  exportMemoPdf: (id) =>
    request(`/credit-memos/${id}/exports/pdf`, { method: "POST" }),
  downloadMemoPdfUrl: (id) => `${BASE}/credit-memos/${id}/exports/pdf`,
};

export const apiBase = BASE;
