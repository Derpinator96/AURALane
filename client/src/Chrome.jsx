import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

const THEME_KEY = "auralane.theme";

// index.html sets data-theme before first paint; this reads it back.
const initialTheme = () =>
  document.documentElement.dataset.theme === "dark" ? "dark" : "light";

export function ThemeToggle() {
  const [theme, setTheme] = useState(initialTheme);
  const dark = theme === "dark";

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = () => {
    const next = dark ? "light" : "dark";
    setTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      // Storage unavailable: the choice lasts until reload.
    }
  };

  return (
    <button type="button" className="theme-toggle" onClick={toggle}
            aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
            title={dark ? "Switch to light mode" : "Switch to dark mode"}>
      {dark ? (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      )}
    </button>
  );
}

// Shared page frame. The non-diagnostic statement is part of the frame, so no
// screen, login included, can render without it.

export function Banner() {
  return (
    <div className="banner" role="note" aria-label="Non-diagnostic notice">
      NON-DIAGNOSTIC. DECISION SUPPORT ONLY.
    </div>
  );
}

export function Header({ session, onSignOut }) {
  const location = useLocation();
  const isRadiologist = session?.user?.groups?.includes("radiologist");
  const isAdmin = session?.user?.groups?.includes("admin");

  return (
    <header className="top">
      <Link to={isRadiologist ? "/" : "/admin"} className="brand">
        AURALane
      </Link>
      <Banner />

      {session && (
        <nav className="header-nav">
          {isRadiologist && (
            <Link
              to="/"
              className={`header-nav-link ${location.pathname === "/" ? "active" : ""}`}
            >
              Worklist
            </Link>
          )}
          {isAdmin && (
            <Link
              to="/admin"
              className={`header-nav-link ${location.pathname.startsWith("/admin") ? "active" : ""}`}
            >
              Admin Console
            </Link>
          )}
        </nav>
      )}

      <div className="header-actions">
        {session && (
          <span className="who">
            <span className="mono">{session.user.email}</span>
            {session.user.groups.map((g) => (
              <span key={g} className="role">[{g}]</span>
            ))}
            <button type="button" onClick={onSignOut}>Sign out</button>
          </span>
        )}
        <ThemeToggle />
      </div>
    </header>
  );
}
