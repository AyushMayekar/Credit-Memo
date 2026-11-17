import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AlertTriangle, Check, X } from "lucide-react";

const UIContext = createContext(null);

const FOCUSABLE =
  'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export function UIProvider({ children }) {
  const [theme, setTheme] = useState(
    () => localStorage.getItem("theme") || "light",
  );
  const [toasts, setToasts] = useState([]);
  const [confirmation, setConfirmation] = useState(null);
  const [loading, setLoading] = useState(null);

  const dialogRef = useRef(null);
  const previousFocusRef = useRef(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    const locked = Boolean(confirmation || loading);
    const previous = document.body.style.overflow;
    if (locked) {
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.body.style.overflow = previous;
    };
  }, [confirmation, loading]);

  useEffect(() => {
    if (!confirmation) return undefined;

    previousFocusRef.current = document.activeElement;
    const node = dialogRef.current;
    const focusables = node
      ? [...node.querySelectorAll(FOCUSABLE)]
      : [];

    (focusables[0] || node)?.focus();

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        confirmation.resolve(false);
        setConfirmation(null);
        return;
      }

      if (event.key !== "Tab" || !node) return;

      const items = [...node.querySelectorAll(FOCUSABLE)];
      if (!items.length) {
        event.preventDefault();
        node.focus();
        return;
      }

      const first = items[0];
      const last = items[items.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus?.();
    };
  }, [confirmation]);

  const dismissToast = (id) =>
    setToasts((current) => current.filter((item) => item.id !== id));

  const toast = (message, type = "success") => {
    const id = crypto.randomUUID();
    setToasts((current) => [...current, { id, message, type }]);
    window.setTimeout(() => dismissToast(id), 4200);
  };

  const askConfirm = (options) =>
    new Promise((resolve) => setConfirmation({ ...options, resolve }));

  const resolveConfirmation = (value) => {
    confirmation?.resolve(value);
    setConfirmation(null);
  };

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

      <div className="toast-stack" aria-live="polite" aria-atomic="false">
        {toasts.map((item) => (
          <div key={item.id} className={`toast toast--${item.type}`}>
            <span className="toast__icon" aria-hidden="true">
              {item.type === "error" ? (
                <AlertTriangle size={13} />
              ) : (
                <Check size={13} />
              )}
            </span>
            <span className="toast__message">{item.message}</span>
            <button
              type="button"
              className="toast__close"
              onClick={() => dismissToast(item.id)}
              aria-label="Dismiss notification"
            >
              <X size={13} />
            </button>
          </div>
        ))}
      </div>

      {confirmation && (
        <div
          className="overlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              resolveConfirmation(false);
            }
          }}
        >
          <section
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            aria-describedby="confirm-description"
            ref={dialogRef}
            tabIndex={-1}
          >
            <span className="dialog__symbol" aria-hidden="true">
              !
            </span>
            <p className="eyebrow">Confirm action</p>
            <h2 id="confirm-title">
              {confirmation.title || "Continue with this action?"}
            </h2>
            <p id="confirm-description" className="muted">
              {confirmation.message}
            </p>
            <div className="dialog__actions">
              <button
                type="button"
                className="btn btn--secondary"
                onClick={() => resolveConfirmation(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => resolveConfirmation(true)}
              >
                Confirm
              </button>
            </div>
          </section>
        </div>
      )}

      {loading && (
        <div className="overlay" role="status" aria-live="assertive">
          <section
            className="dialog dialog--loading"
            aria-labelledby="loading-title"
          >
            <p className="eyebrow">Please wait</p>
            <h2 id="loading-title">{loading.title}</h2>
            <p className="muted">{loading.message}</p>
            <div className="loader" aria-hidden="true">
              <span />
            </div>
          </section>
        </div>
      )}
    </UIContext.Provider>
  );
}

export const useUI = () => useContext(UIContext);
