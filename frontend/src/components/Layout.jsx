import { NavLink, Outlet, useLocation } from "react-router";
import { FilePlus2, LayoutDashboard, Moon, Sun } from "lucide-react";
import { useUI } from "../context/UIContext";

const pageTitles = {
  "/": ["Overview", "Monitor assessments and continue your credit workflow."],
  "/new": ["New assessment", "Capture borrower and facility details."],
};

export default function Layout() {
  const { pathname } = useLocation();
  const { theme, setTheme } = useUI();
  const isWorkspace = pathname.startsWith("/applications/");
  const [title, description] = isWorkspace
    ? ["Application workspace", "Review documents, ask questions, and prepare the memo."]
    : pageTitles[pathname] || ["Credit Memo", "Evidence-led credit analysis."];

  return (
    <div className="app-shell">
      <aside className="sidebar clay">
        <div className="brand">
          <span className="brand-mark">CM</span>
          <div>
            <strong>Credit Memo</strong>
            <small>Evidence Led Analysis</small>
          </div>
        </div>

        <nav aria-label="Primary navigation">
          <NavLink to="/" end>
            <LayoutDashboard />
            <span>Overview</span>
          </NavLink>
          <NavLink to="/new">
            <FilePlus2 />
            <span>New Assessment</span>
          </NavLink>
        </nav>

        <div className="sidebar-footer">
          <span className="appearance-label">Appearance</span>
          <button
            type="button"
            className="theme-switch"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label="Toggle color theme"
          >
            <Sun />
            <span className={`switch-track ${theme === "dark" ? "dark" : ""}`}>
              <span />
            </span>
            <Moon />
          </button>
        </div>
      </aside>

      <main className="main-area">
        <header className="page-header">
          <p className="eyebrow">Credit intelligence workspace</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </header>
        <div className="page"><Outlet /></div>
      </main>
    </div>
  );
}
