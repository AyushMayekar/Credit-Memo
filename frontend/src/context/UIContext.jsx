import { createContext, useContext, useEffect, useMemo, useState } from "react";

const UIContext = createContext(null);

export function UIProvider({ children }) {
  const [theme, setTheme] = useState(localStorage.getItem("theme") || "light");
  const [toasts, setToasts] = useState([]);
  const [confirmation, setConfirmation] = useState(null);
  const [loading, setLoading] = useState(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toast = (message, type = "success") => {
    const id = crypto.randomUUID();
    setToasts((current) => [...current, { id, message, type }]);
    window.setTimeout(
      () => setToasts((current) => current.filter((item) => item.id !== id)),
      3400,
    );
  };

  const askConfirm = (options) =>
    new Promise((resolve) => setConfirmation({ ...options, resolve }));

  const runWithLoading = async (
    task,
    {
      title = "Working on your request",
      message = "This may take a moment.",
      success,
    } = {},
  ) => {
    setLoading({ title, message });
    try {
      const result = await task();
      if (success) toast(success);
      return result;
    } catch (error) {
      toast(error.message || "Something went wrong", "error");
      throw error;
    } finally {
      setLoading(null);
    }
  };

  const value = useMemo(
    () => ({ theme, setTheme, toast, askConfirm, runWithLoading, loading }),
    [theme, loading],
  );

  return (
    <UIContext.Provider value={value}>
      {children}

      <div className="toast-stack" aria-live="polite">
        {toasts.map((item) => (
          <div key={item.id} className={`toast toast-${item.type}`}>
            <span className="toast-icon">{item.type === "error" ? "!" : "✓"}</span>
            <span>{item.message}</span>
          </div>
        ))}
      </div>

      {confirmation && (
        <div className="modal-backdrop" role="presentation">
          <section className="modal clay" role="dialog" aria-modal="true">
            <span className="modal-symbol">?</span>
            <p className="eyebrow">Please confirm</p>
            <h2>{confirmation.title || "Continue with this action?"}</h2>
            <p className="muted">{confirmation.message}</p>
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => {
                  confirmation.resolve(false);
                  setConfirmation(null);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="button danger"
                onClick={() => {
                  confirmation.resolve(true);
                  setConfirmation(null);
                }}
              >
                Confirm
              </button>
            </div>
          </section>
        </div>
      )}

      {loading && (
        <div className="loading-backdrop" role="status" aria-live="assertive">
          <section className="loading-card clay">
            <div className="orb-loader" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <p className="eyebrow">Please wait</p>
            <h2>{loading.title}</h2>
            <p className="muted">{loading.message}</p>
            <div className="indeterminate"><span /></div>
          </section>
        </div>
      )}
    </UIContext.Provider>
  );
}

export const useUI = () => useContext(UIContext);
