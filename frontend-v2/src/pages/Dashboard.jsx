import { ArrowUpRight, AlertTriangle, FilePlus2, Plus, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import StatusChip from "../components/StatusChip";

export default function Dashboard() {
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const result = await api.listApplications();
      setApplications(Array.isArray(result) ? result : []);
    } catch (failure) {
      setError(failure.message || "Unable to load assessments.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const stats = [
    { label: "Total assessments", value: applications.length },
    {
      label: "In progress",
      value: applications.filter(
        (item) => !["MEMO_READY", "FAILED"].includes(item.status),
      ).length,
    },
    {
      label: "Memos ready",
      value: applications.filter((item) => item.status === "MEMO_READY")
        .length,
    },
    {
      label: "Needs attention",
      value: applications.filter((item) => item.status === "FAILED").length,
    },
  ];

  return (
    <div className="stack">
      <section className="stats" aria-label="Assessment summary">
        {stats.map((stat) => (
          <div className="stat" key={stat.label}>
            <span className="stat__label">{stat.label}</span>
            <strong className="stat__value">
              {loading ? "—" : stat.value}
            </strong>
          </div>
        ))}
      </section>

      <section className="panel" aria-labelledby="applications-title">
        <div className="panel__head">
          <div>
            <p className="eyebrow">Applications</p>
            <h2 id="applications-title">Recent assessments</h2>
            <p className="panel__description">
              Open an assessment to review evidence and prepare a memo.
            </p>
          </div>
          <Link className="btn btn--primary" to="/new">
            <Plus size={15} aria-hidden="true" />
            New assessment
          </Link>
        </div>

        {loading && (
          <div className="table-wrap">
            <table className="data-table" aria-label="Loading assessments">
              <thead>
                <tr>
                  <th scope="col">Borrower</th>
                  <th scope="col">Reference</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="ta-right">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {[0, 1, 2, 3].map((row) => (
                  <tr key={row}>
                    <td>
                      <span className="skeleton skeleton--text" />
                    </td>
                    <td>
                      <span className="skeleton skeleton--short" />
                    </td>
                    <td>
                      <span className="skeleton skeleton--chip" />
                    </td>
                    <td>
                      <span className="skeleton skeleton--short skeleton--right" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!loading && error && (
          <div className="state state--error">
            <AlertTriangle size={20} aria-hidden="true" />
            <div>
              <h3>Assessments could not be loaded</h3>
              <p>{error}</p>
            </div>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={load}
            >
              <RefreshCw size={15} aria-hidden="true" />
              Retry
            </button>
          </div>
        )}

        {!loading && !error && !applications.length && (
          <div className="empty">
            <FilePlus2 size={22} aria-hidden="true" />
            <h3>No assessments yet</h3>
            <p>
              Create your first assessment to upload source documents and
              build a credit memo.
            </p>
            <Link className="btn btn--primary" to="/new">
              <Plus size={15} aria-hidden="true" />
              New assessment
            </Link>
          </div>
        )}

        {!loading && !error && applications.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Borrower</th>
                  <th scope="col">Reference</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="ta-right">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {applications.map((application) => {
                  const target = `/applications/${application.application_reference}`;

                  return (
                    <tr key={application.application_reference}>
                      <td>
                        <Link className="row-link" to={target}>
                          {application.borrower_name}
                        </Link>
                      </td>
                      <td>
                        <span className="mono">
                          {application.application_reference}
                        </span>
                      </td>
                      <td>
                        <StatusChip status={application.status} />
                      </td>
                      <td className="ta-right">
                        <Link
                          className="btn btn--ghost btn--sm"
                          to={target}
                          aria-label={`Open ${application.borrower_name} assessment`}
                        >
                          Open
                          <ArrowUpRight size={14} aria-hidden="true" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
