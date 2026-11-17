import { ArrowRight, FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";

export default function Dashboard() {
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listApplications()
      .then(setApplications)
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <section className="hero clay">
        <div>
          <span className="pill">Evidence-first workflow</span>
          <h2>Move from source documents to a reviewable credit memo.</h2>
          <p>
            Select reliable evidence, ask grounded questions, and create a
            structured draft with traceable sources.
          </p>
        </div>
        <Link className="button accent" to="/new">
          Create assessment <ArrowRight size={18} />
        </Link>
      </section>

      <section>
        <div className="section-title compact">
          <div>
            <p className="eyebrow">Applications</p>
            <h2>Recent assessments</h2>
          </div>
          <span className="count-badge">{applications.length}</span>
        </div>

        {loading ? (
          <div className="card-grid">
            {[1, 2].map((item) => <div key={item} className="skeleton-card clay" />)}
          </div>
        ) : (
          <div className="card-grid">
            {applications.map((application) => (
              <Link
                className="clay app-card"
                to={`/applications/${application.application_reference}`}
                key={application.application_reference}
              >
                <div className="app-card-top">
                  <span className={`status status-${application.status.toLowerCase()}`}>
                    {application.status.replaceAll("_", " ")}
                  </span>
                  <ArrowRight className="card-arrow" />
                </div>
                <span className="card-icon"><FileText /></span>
                <h3>{application.borrower_name}</h3>
                <p>{application.application_reference}</p>
                <span className="open-label">Open workspace</span>
              </Link>
            ))}
            {!applications.length && (
              <div className="empty clay">No assessments have been created yet.</div>
            )}
          </div>
        )}
      </section>
    </>
  );
}
