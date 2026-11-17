import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useUI } from "../context/UIContext";

export default function ConfirmButton({
  children,
  title,
  message,
  onConfirm,
  className = "btn btn--primary",
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
      // runWithLoading displays the error notification.
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
      {busy ? (
        <>
          <Loader2 size={15} className="spin" aria-hidden="true" />
          Working…
        </>
      ) : (
        children
      )}
    </button>
  );
}
