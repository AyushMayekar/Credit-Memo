import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api/client";
import { useUI } from "../context/UIContext";

const INITIAL_FORM = {
  legal_name: "",
  borrower_type: "CORPORATE",
  industry: "",
  country: "",
  loan_amount: "",
  currency: "INR",
  loan_purpose: "",
  tenure_months: 36,
};

export default function NewApplication() {
  const navigate = useNavigate();
  const { askConfirm, runWithLoading } = useUI();
  const [form, setForm] = useState(INITIAL_FORM);

  const change = (event) =>
    setForm((current) => ({
      ...current,
      [event.target.name]: event.target.value,
    }));

  async function submit(event) {
    event.preventDefault();

    const approved = await askConfirm({
      title: "Create this assessment?",
      message:
        "Please confirm that the borrower and facility details are correct.",
    });
    if (!approved) return;

    try {
      const result = await runWithLoading(
        () =>
          api.createApplication({
            borrower: {
              legal_name: form.legal_name,
              borrower_type: form.borrower_type,
              industry: form.industry || null,
              country: form.country || null,
            },
            facility: {
              loan_amount: form.loan_amount,
              currency: form.currency,
              loan_purpose: form.loan_purpose,
              tenure_months: Number(form.tenure_months),
            },
          }),
        {
          title: "Creating assessment",
          message:
            "Setting up the borrower workspace and facility request.",
          success: "Assessment created successfully",
        },
      );

      navigate(
        `/applications/${result.application_reference}`,
      );
    } catch {
      // Central error handling.
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <div className="form-layout">
        <section className="panel" aria-labelledby="borrower-heading">
          <div className="panel__head panel__head--compact">
            <div>
              <p className="eyebrow">Borrower</p>
              <h2 id="borrower-heading">Borrower information</h2>
            </div>
            <span className="panel__index mono">01</span>
          </div>

          <div className="panel__body">
            <div className="field-grid">
              <label className="field field--full">
                <span className="field__label">
                  Legal name <em>Required</em>
                </span>
                <input
                  className="input"
                  name="legal_name"
                  required
                  autoComplete="organization"
                  value={form.legal_name}
                  onChange={change}
                />
              </label>

              <label className="field">
                <span className="field__label">
                  Borrower type <em>Required</em>
                </span>
                <select
                  className="input"
                  name="borrower_type"
                  value={form.borrower_type}
                  onChange={change}
                >
                  <option value="CORPORATE">Corporate</option>
                  <option value="SME">Small or medium enterprise</option>
                </select>
              </label>

              <label className="field">
                <span className="field__label">Industry</span>
                <input
                  className="input"
                  name="industry"
                  value={form.industry}
                  onChange={change}
                />
              </label>

              <label className="field">
                <span className="field__label">Country</span>
                <input
                  className="input"
                  name="country"
                  autoComplete="country-name"
                  value={form.country}
                  onChange={change}
                />
              </label>
            </div>
          </div>
        </section>

        <section className="panel" aria-labelledby="facility-heading">
          <div className="panel__head panel__head--compact">
            <div>
              <p className="eyebrow">Facility</p>
              <h2 id="facility-heading">Facility request</h2>
            </div>
            <span className="panel__index mono">02</span>
          </div>

          <div className="panel__body">
            <div className="field-grid">
              <label className="field">
                <span className="field__label">
                  Amount <em>Required</em>
                </span>
                <input
                  className="input"
                  name="loan_amount"
                  type="number"
                  min="0"
                  step="any"
                  inputMode="decimal"
                  required
                  value={form.loan_amount}
                  onChange={change}
                />
              </label>

              <label className="field">
                <span className="field__label">
                  Currency <em>Required</em>
                </span>
                <select
                  className="input"
                  name="currency"
                  value={form.currency}
                  onChange={change}
                >
                  <option value="INR">INR</option>
                  <option value="GBP">GBP</option>
                  <option value="USD">USD</option>
                  <option value="EUR">EUR</option>
                </select>
              </label>

              <label className="field">
                <span className="field__label">
                  Tenure in months <em>Required</em>
                </span>
                <input
                  className="input"
                  name="tenure_months"
                  type="number"
                  min="1"
                  required
                  value={form.tenure_months}
                  onChange={change}
                />
              </label>

              <label className="field field--full">
                <span className="field__label">
                  Purpose <em>Required</em>
                </span>
                <textarea
                  className="input input--textarea"
                  name="loan_purpose"
                  required
                  value={form.loan_purpose}
                  onChange={change}
                />
              </label>
            </div>
          </div>
        </section>
      </div>

      <div className="form-bar">
        <p className="muted">
          Fields marked <em>Required</em> must be completed before the
          assessment is created.
        </p>
        <div className="form-bar__actions">
          <Link className="btn btn--ghost" to="/">
            Cancel
          </Link>
          <button className="btn btn--primary" type="submit">
            Create assessment
          </button>
        </div>
      </div>
    </form>
  );
}
