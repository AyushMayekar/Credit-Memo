import { useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import { useUI } from "../context/UIContext";

export default function NewApplication() {
  const navigate = useNavigate();
  const { askConfirm, runWithLoading } = useUI();
  const [form, setForm] = useState({
    legal_name: "",
    borrower_type: "CORPORATE",
    industry: "",
    country: "",
    loan_amount: "",
    currency: "INR",
    loan_purpose: "",
    tenure_months: 36,
  });

  const change = (event) =>
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    const approved = await askConfirm({
      title: "Create this assessment?",
      message: "Please confirm that the borrower and facility details are correct.",
    });
    if (!approved) return;

    try {
      const result = await runWithLoading(
        () => api.createApplication({
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
          message: "Setting up the borrower workspace and facility request.",
          success: "Assessment created successfully",
        },
      );
      navigate(`/applications/${result.application_reference}`);
    } catch {
      // Error notification is handled centrally.
    }
  }

  return (
    <form className="form clay" onSubmit={submit}>
      <div className="form-intro">
        <p className="eyebrow">Application details</p>
        <h2>Borrower and facility details</h2>
        <p className="muted">Fields marked with an asterisk are required.</p>
      </div>

      <fieldset>
        <legend>Borrower information</legend>
        <div className="form-grid">
          <label>
            Legal name *
            <input name="legal_name" required value={form.legal_name} onChange={change} />
          </label>
          <label>
            Borrower type *
            <select name="borrower_type" value={form.borrower_type} onChange={change}>
              <option value="CORPORATE">Corporate</option>
              <option value="SME">Small or medium enterprise</option>
            </select>
          </label>
          <label>
            Industry
            <input name="industry" value={form.industry} onChange={change} />
          </label>
          <label>
            Country
            <input name="country" value={form.country} onChange={change} />
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Facility request</legend>
        <div className="form-grid">
          <label>
            Amount *
            <input name="loan_amount" type="number" min="0" required value={form.loan_amount} onChange={change} />
          </label>
          <label>
            Currency *
            <select name="currency" value={form.currency} onChange={change}>
              <option value="INR">INR</option>
              <option value="GBP">GBP</option>
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
            </select>
          </label>
          <label className="wide">
            Purpose *
            <textarea name="loan_purpose" required value={form.loan_purpose} onChange={change} />
          </label>
          <label>
            Tenure in months *
            <input name="tenure_months" type="number" min="1" required value={form.tenure_months} onChange={change} />
          </label>
        </div>
      </fieldset>

      <div className="form-actions">
        <button className="button primary" type="submit">Create assessment</button>
      </div>
    </form>
  );
}
