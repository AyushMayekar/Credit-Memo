import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { Moon, Sun } from "lucide-react";
import { useUI } from "../context/UIContext";

const pageMeta = {
  "/": {
    eyebrow: "Workspace",
    title: "Overview",
    description:
      "Monitor assessments and continue your credit workflow.",
  },
  "/new": {
    eyebrow: "Workspace",
    title: "New assessment",
    description: "Capture borrower and facility details.",
  },
};

export default function Layout() {
  const { pathname } = useLocation();
  const { theme, setTheme } = useUI();
  const isWorkspace = pathname.startsWith("/applications/");
  const meta = isWorkspace ? null : pageMeta[pathname] || pageMeta["/"];

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [pathname]);

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="topbar">
        <div className="topbar__inner">
          <NavLink to="/" className="brand" aria-label="Credit Memo home">
            <span className="brand__mark" aria-hidden="true">
              CM
            </span>
            <span className="brand__name">Credit Memo</span>
          </NavLink>

          <nav className="nav" aria-label="Primary navigation">
            <NavLink to="/" end>
              Overview
            </NavLink>
            <NavLink to="/new">New assessment</NavLink>
          </nav>

          <div className="topbar__actions">
            <div
              className="theme-toggle"
              role="group"
              aria-label="Color theme"
            >
              <button
                type="button"
                onClick={() => setTheme("light")}
                aria-pressed={theme === "light"}
                title="Light theme"
              >
                <Sun size={14} aria-hidden="true" />
                <span className="sr-only">Light theme</span>
              </button>
              <button
                type="button"
                onClick={() => setTheme("dark")}
                aria-pressed={theme === "dark"}
                title="Dark theme"
              >
                <Moon size={14} aria-hidden="true" />
                <span className="sr-only">Dark theme</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="main" id="main">
        <div className="container">
          {meta && (
            <header className="page-head">
              <div>
                <p className="eyebrow">{meta.eyebrow}</p>
                <h1>{meta.title}</h1>
                <p className="page-head__subtitle">
                  {meta.description}
                </p>
              </div>
            </header>
          )}

          <Outlet />
        </div>
      </main>
    </div>
  );
}
