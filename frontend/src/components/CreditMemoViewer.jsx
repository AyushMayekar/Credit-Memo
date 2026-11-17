import { Download, ExternalLink } from "lucide-react";

const sectionLabels = {
  executive_summary: "Executive Summary",
  borrower_profile: "Borrower Profile",
  facility_request: "Facility Request",
  business_and_industry_analysis: "Business and Industry Analysis",
  management_ownership_governance: "Management, Ownership and Governance",
  financial_analysis: "Financial Analysis",
  existing_debt_and_repayment_capacity:
    "Existing Debt and Repayment Capacity",
  security_and_collateral: "Security and Collateral",
  key_credit_strengths: "Key Credit Strengths",
  key_credit_risks: "Key Credit Risks",
  risk_mitigants: "Risk Mitigants",
  policy_compliance_and_exceptions: "Policy Compliance and Exceptions",
  proposed_terms_and_conditions: "Proposed Terms and Conditions",
  credit_recommendation: "Credit Recommendation",
};

const itemSectionKeys = new Set([
  "key_credit_strengths",
  "key_credit_risks",
  "risk_mitigants",
]);

function formatLabel(value = "") {
  return value.replaceAll("_", " ");
}

function Narrative({ value }) {
  if (!value) return null;

  if (value.status !== "available" || !value.text) {
    return (
      <p className="empty-section">
        {formatLabel(value.status || "not disclosed")}
      </p>
    );
  }

  return (
    <>
      <p>{value.text}</p>

      {!!value.evidence?.length && (
        <div className="memo-citations">
          {value.evidence.map((evidence, index) => (
            <span key={`${evidence.source_id}-${index}`}>
              {evidence.source_id}
              {evidence.page_start
                ? ` · p.${evidence.page_start}`
                : ""}
            </span>
          ))}
        </div>
      )}

      {!!value.caveats?.length && (
        <ul className="memo-caveats">
          {value.caveats.map((caveat, index) => (
            <li key={index}>{caveat}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function Metrics({ metrics = [] }) {
  if (!metrics.length) return null;

  return (
    <div className="memo-metric-grid">
      {metrics.map((metric, index) => (
        <div
          className="memo-metric"
          key={`${metric.metric_name}-${metric.period}-${index}`}
        >
          <small>{formatLabel(metric.metric_name)}</small>
          <strong>
            {metric.value !== null && metric.value !== undefined
              ? metric.value
              : "Not disclosed"}
          </strong>
          <span>
            {metric.unit}
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
    <>
      <Narrative value={section.summary} />
      <Metrics metrics={section.metrics} />

      {section.subsections?.map((subsection) => (
        <div className="memo-subsection" key={subsection.key}>
          <h4>{subsection.title}</h4>
          <Narrative value={subsection.narrative} />
          <Metrics metrics={subsection.metrics} />
        </div>
      ))}
    </>
  );
}

function ItemSection({ section }) {
  if (!section) return null;

  return (
    <>
      <Narrative value={section.summary} />

      <div className="credit-item-list">
        {section.items?.map((item) => (
          <article key={item.item_id}>
            <div>
              <strong>{item.title}</strong>
              <span className={`severity severity-${item.severity}`}>
                {formatLabel(item.severity)}
              </span>
            </div>
            <p>{item.description}</p>

            {!!item.evidence?.length && (
              <div className="memo-citations">
                {item.evidence.map((evidence, index) => (
                  <span key={`${evidence.source_id}-${index}`}>
                    {evidence.source_id}
                    {evidence.page_start
                      ? ` · p.${evidence.page_start}`
                      : ""}
                  </span>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </>
  );
}

function FinancialSection({ section }) {
  if (!section) return null;

  return (
    <>
      {section.summary && <Narrative value={section.summary} />}
      <Metrics metrics={section.ratios} />

      {["profitability", "balance_sheet", "cash_flow"].map((key) => {
        const subsection = section[key];
        if (!subsection) return null;

        return (
          <div className="memo-subsection" key={key}>
            <h4>{formatLabel(key)}</h4>
            <StandardSection section={subsection} />
          </div>
        );
      })}
    </>
  );
}

function RecommendationSection({ section }) {
  if (!section) return null;

  return (
    <>
      <Narrative value={section.rationale} />

      {!!section.conditions?.length && (
        <div className="memo-subsection">
          <h4>Conditions</h4>
          <ul>
            {section.conditions.map((condition, index) => (
              <li key={index}>{condition}</li>
            ))}
          </ul>
        </div>
      )}

      {!!section.unresolved_issues?.length && (
        <div className="memo-subsection">
          <h4>Unresolved issues</h4>
          <ul>
            {section.unresolved_issues.map((issue, index) => (
              <li key={index}>{issue}</li>
            ))}
          </ul>
        </div>
      )}
    </>
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
  if (!memo) return null;

  return (
    <div className="structured-memo">
      <div className="memo-toolbar">
        <div>
          <p className="eyebrow">Structured credit memo</p>
          <h3>{memo.report_metadata?.report_title}</h3>
          <span>
            {memo.report_metadata?.period_label} · Version{" "}
            {memo.report_metadata?.memo_version}
          </span>
        </div>

        <div className="memo-toolbar-actions">
          <a
            className="button secondary"
            href={previewUrl}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={16} /> Preview
          </a>

          <button
            type="button"
            className="button primary"
            onClick={onExport}
          >
            <Download size={16} /> Export PDF
          </button>

          {pdfUrl && (
            <a className="button accent" href={pdfUrl}>
              Download PDF
            </a>
          )}
        </div>
      </div>

      {Object.entries(sectionLabels).map(([sectionKey, label]) => {
        const section = memo[sectionKey];
        if (!section) return null;

        const status =
          section.recommendation_status || section.status || "";

        return (
          <section className="memo-view-section" key={sectionKey}>
            <div className="memo-section-heading">
              <h3>{label}</h3>
              {status && (
                <span className="status">
                  {formatLabel(status)}
                </span>
              )}
            </div>

            <SectionContent
              sectionKey={sectionKey}
              section={section}
            />
          </section>
        );
      })}
    </div>
  );
}
