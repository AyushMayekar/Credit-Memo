import { useState } from "react";
import { useUI } from "../context/UIContext";

export default function ConfirmButton({
  children,
  title,
  message,
  onConfirm,
  className = "button primary",
  success = "Completed successfully",
  loadingTitle = "Processing your request",
  loadingMessage = "Please keep this page open while the request completes.",
  disabled = false,
}) {
  const [busy, setBusy] = useState(false);
  const { askConfirm, runWithLoading } = useUI();

  async function handleClick() {
    const approved = await askConfirm({ title, message });
    if (!approved) return;
    setBusy(true);
    try {
      await runWithLoading(onConfirm, {
        title: loadingTitle,
        message: loadingMessage,
        success,
      });
    } catch {
      // runWithLoading already shows the error toast.
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className={className}
      disabled={disabled || busy}
      onClick={handleClick}
    >
      {busy ? <><span className="button-spinner" /> Working…</> : children}
    </button>
  );
}
