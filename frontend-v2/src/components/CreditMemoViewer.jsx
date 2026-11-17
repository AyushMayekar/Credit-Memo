import { useEffect, useState } from "react";
import {
  ChevronDown,
  Download,
  ExternalLink,
  FileDown,
} from "lucide-react";

const sectionLabels = {
  executive_summary: "Executive Summary",
  borrower_profile: "Borrower Profile",
  facility_request: "Facility Request",
  business_and_industry_analysis: "Business and Industry Analysis",
  management_ownership_governance:
    "Management, Ownership and Governance",
  financial_analysis: "Financial Analysis",
  existing_debt_and_repayment_capacity:
    "Existing Debt and Repayment Capacity",
  security_and_collateral: "Security and Collateral",
  key_credit_strengths: "Key Credit Strengths",
  key_credit_risks: "Key Credit Risks",
  risk_mitigants: "Risk Mitigants",
  policy_compliance_and_exceptions:
    "Policy Compliance and Exceptions",
  proposed_terms_and_conditions: "Proposed Terms and Conditions",
  credit_recommendation: "Credit Recommendation",
};

const itemSectionKeys = new Set([
  "key_credit_strengths",
  "key_credit_risks",
  "risk_mitigants",
]);

function humanize(value) {
  const text = String(value || "not disclosed").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatValue(value) {
  if (value === null || value === undefined) return "Not disclosed";
  if (typeof value === "number") {
    return value.toLocaleString();
  }
  return String(value);
}

function Evidence({ items = [] }) {
  if (!items.length) return null;

  return (
    <div className="evidence" aria-label="Sources">
      {items.map((item, index) => (
        <span key={`${item.source_id}-${index}`} className="evidence__chip">
          {item.source_id}
          {item.page_start ? ` · p.${item.page_start}` : ""}
        </span>
      ))}
    </div>
  );
}

function Caveats({ items = [] }) {
  if (!items.length) return null;

  return (
    <div className="caveats">
      <span className="caveats__label">Caveats</span>
      <ul>
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Narrative({ value }) {
  if (!value) return null;

  if (value.status !== "available" || !value.text) {
    return (
      <p className="empty-note">{humanize(value.status || "not disclosed")}</p>
    );
  }

  return (
    <div className="narrative">
      <p>{value.text}</p>
      <Evidence items={value.evidence} />
      <Caveats items={value.caveats} />
    </div>
  );
}

function Metrics({ metrics = [] }) {
  if (!metrics.length) return null;

  return (
    <div className="metrics">
      {metrics.map((metric, index) => (
        <div
          className="metric"
          key={`${metric.metric_name}-${metric.period}-${index}`}
        >
          <span className="metric__label">
            {humanize(metric.metric_name)}
          </span>
          <strong className="metric__value">
            {formatValue(metric.value)}
          </strong>
          <span className="metric__meta">
            {metric.unit && metric.unit !== "not_specified"
              ? humanize(metric.unit)
              : "Unit not specified"}
            {metric.period ? ` · ${metric.period}` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

function StandardSection({ section }) {
  if (!section) return null;

  return (
    <div className="memo-content">
      <Narrative value={section.summary} />
      <Metrics metrics={section.metrics} />

      {section.subsections?.map((subsection) => (
        <div className="memo-subsection" key={subsection.key}>
          <h5>{subsection.title}</h5>
          <Narrative value={subsection.narrative} />
          <Metrics metrics={subsection.metrics} />
        </div>
      ))}
    </div>
  );
}

function ItemSection({ section }) {
  if (!section) return null;

  return (
    <div className="memo-content">
      <Narrative value={section.summary} />

      {!section.items?.length ? (
        <p className="empty-note">No information was disclosed.</p>
      ) : (
        <div className="items">
          {section.items.map((item) => (
            <article className="item" key={item.item_id}>
              <div className="item__head">
                <h5>{item.title}</h5>
                <span
                  className={`severity severity--${String(
                    item.severity || "not_assessed",
                  ).toLowerCase()}`}
                >
                  {humanize(item.severity)}
                </span>
              </div>
              <p>{item.description}</p>
              <Evidence items={item.evidence} />
              <Caveats items={item.caveats} />
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function FinancialSection({ section }) {
  if (!section) return null;

  return (
    <div className="memo-content">
      <Narrative value={section.summary} />
      <Metrics metrics={section.ratios} />

      {["profitability", "balance_sheet", "cash_flow"].map((key) => {
        const subsection = section[key];
        if (!subsection) return null;

        return (
          <div className="memo-subsection" key={key}>
            <h5>{humanize(key)}</h5>
            <StandardSection section={subsection} />
          </div>
        );
      })}
    </div>
  );
}

function RecommendationSection({ section }) {
  if (!section) return null;

  const amount = section.recommended_amount;

  return (
    <div className="memo-content">
      <Narrative value={section.rationale} />

      {amount?.value !== null && amount?.value !== undefined && (
        <div className="recommendation-amount">
          <span>Recommended amount</span>
          <strong>{formatValue(amount.value)}</strong>
          <small>
            {amount.unit ? humanize(amount.unit) : "Unit not specified"}
          </small>
        </div>
      )}

      {!!section.conditions?.length && (
        <div className="memo-subsection">
          <h5>Conditions</h5>
          <ul className="plain-list">
            {section.conditions.map((condition, index) => (
              <li key={index}>{condition}</li>
            ))}
          </ul>
        </div>
      )}

      {!!section.required_approvals?.length && (
        <div className="memo-subsection">
          <h5>Required approvals</h5>
          <ul className="plain-list">
            {section.required_approvals.map((approval, index) => (
              <li key={index}>{approval}</li>
            ))}
          </ul>
        </div>
      )}

      {!!section.unresolved_issues?.length && (
        <div className="memo-subsection">
          <h5>Unresolved issues</h5>
          <ul className="plain-list">
            {section.unresolved_issues.map((issue, index) => (
              <li key={index}>{issue}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function QualitySection({ quality }) {
  if (!quality) return null;

  const groups = [
    ["Missing information", quality.missing_information],
    ["Conflicts", quality.conflicts],
    ["Pending calculations", quality.pending_calculations],
    ["Review items", quality.review_items],
  ].filter(([, items]) => items?.length);

  return (
    <div className="memo-content">
      <div className="quality-head">
        <span className="muted">Overall quality status</span>
        <span className="quality-status">
          {humanize(quality.overall_quality_status)}
        </span>
      </div>

      {!groups.length && (
        <p className="empty-note">No quality issues were flagged.</p>
      )}

      {groups.map(([label, items]) => (
        <div className="memo-subsection" key={label}>
          <h5>{label}</h5>
          <ul className="plain-list">
            {items.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function SectionContent({ sectionKey, section }) {
  if (itemSectionKeys.has(sectionKey)) {
    return <ItemSection section={section} />;
  }

  if (sectionKey === "financial_analysis") {
    return <FinancialSection section={section} />;
  }

  if (sectionKey === "credit_recommendation") {
    return <RecommendationSection section={section} />;
  }

  return <StandardSection section={section} />;
}

export default function CreditMemoViewer({
  memo,
  onExport,
  pdfUrl,
  previewUrl,
}) {
  const [activeSection, setActiveSection] = useState("executive_summary");
  const [closedSections, setClosedSections] = useState({});

  const entries = Object.entries(sectionLabels).filter(
    ([key]) => memo?.[key],
  );
  const quality = memo?.missing_information_and_quality_flags;
  const hasQuality = Boolean(quality);

  useEffect(() => {
    if (!memo) return undefined;

    const nodes = [...document.querySelectorAll("[data-memo-section]")];
    if (!nodes.length || !("IntersectionObserver" in window)) {
      return undefined;
    }

    const observer = new IntersectionObserver(
      (observed) => {
        const visible = observed
          .filter((entry) => entry.isIntersecting)
          .sort(
            (a, b) =>
              a.boundingClientRect.top - b.boundingClientRect.top,
          );

        if (visible[0]) {
          setActiveSection(
            visible[0].target.id.replace("memo-", ""),
          );
        }
      },
      { rootMargin: "-96px 0px -62% 0px", threshold: 0 },
    );

    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [memo]);

  if (!memo) return null;

  const toggleSection = (key) =>
    setClosedSections((current) => ({
      ...current,
      [key]: !current[key],
    }));

  return (
    <div className="memo">
      <div className="memo__head">
        <div>
          <p className="eyebrow">Structured credit memo</p>
          <h3>{memo.report_metadata?.report_title || "Credit memo"}</h3>
          <p className="memo__meta">
            {memo.report_metadata?.period_label || "Review period"}
            <span aria-hidden="true"> · </span>
            Version {memo.report_metadata?.memo_version ?? "1"}
          </p>
        </div>

        <div className="memo__actions">
          <a
            className="btn btn--secondary"
            href={previewUrl}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={15} aria-hidden="true" />
            Preview
          </a>
          <button
            type="button"
            className="btn btn--primary"
            onClick={onExport}
          >
            <Download size={15} aria-hidden="true" />
            Export PDF
          </button>
          {pdfUrl && (
            <a className="btn btn--ghost" href={pdfUrl}>
              <FileDown size={15} aria-hidden="true" />
              Download PDF
            </a>
          )}
        </div>
      </div>

      <div className="memo__layout">
        <nav className="memo__toc" aria-label="Memo sections">
          <p className="eyebrow">Contents</p>
          <ol>
            {entries.map(([key, label], index) => (
              <li key={key}>
                <a
                  href={`#memo-${key}`}
                  className={activeSection === key ? "is-active" : ""}
                  onClick={() => setActiveSection(key)}
                >
                  <span className="memo__toc-num">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span>{label}</span>
                </a>
              </li>
            ))}
            {hasQuality && (
              <li>
                <a
                  href="#memo-quality"
                  className={activeSection === "quality" ? "is-active" : ""}
                  onClick={() => setActiveSection("quality")}
                >
                  <span className="memo__toc-num">
                    {String(entries.length + 1).padStart(2, "0")}
                  </span>
                  <span>Quality flags</span>
                </a>
              </li>
            )}
          </ol>
        </nav>

        <div className="memo__body">
          {entries.map(([key, label], index) => {
            const section = memo[key];
            const status =
              section.recommendation_status || section.status || "";
            const isClosed = Boolean(closedSections[key]);

            return (
              <section
                className="memo-section"
                id={`memo-${key}`}
                data-memo-section
                key={key}
              >
                <h4>
                  <button
                    type="button"
                    className="memo-section__toggle"
                    aria-expanded={!isClosed}
                    aria-controls={`memo-panel-${key}`}
                    onClick={() => toggleSection(key)}
                  >
                    <span className="memo-section__num" aria-hidden="true">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="memo-section__title">{label}</span>
                    {status && (
                      <span className="memo-section__status">
                        {humanize(status)}
                      </span>
                    )}
                    <ChevronDown
                      size={16}
                      className="memo-section__chevron"
                      aria-hidden="true"
                    />
                  </button>
                </h4>

                {!isClosed && (
                  <div
                    className="memo-section__body"
                    id={`memo-panel-${key}`}
                  >
                    <SectionContent sectionKey={key} section={section} />
                  </div>
                )}
              </section>
            );
          })}

          {hasQuality && (
            <section
              className="memo-section"
              id="memo-quality"
              data-memo-section
            >
              <h4>
                <button
                  type="button"
                  className="memo-section__toggle"
                  aria-expanded={!closedSections.quality}
                  aria-controls="memo-panel-quality"
                  onClick={() => toggleSection("quality")}
                >
                  <span className="memo-section__num" aria-hidden="true">
                    {String(entries.length + 1).padStart(2, "0")}
                  </span>
                  <span className="memo-section__title">
                    Missing information and quality flags
                  </span>
                  <span className="memo-section__status">
                    {humanize(quality.overall_quality_status)}
                  </span>
                  <ChevronDown
                    size={16}
                    className="memo-section__chevron"
                    aria-hidden="true"
                  />
                </button>
              </h4>

              {!closedSections.quality && (
                <div
                  className="memo-section__body"
                  id="memo-panel-quality"
                >
                  <QualitySection quality={quality} />
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
