import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "./components/Icons.jsx";

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
    <button type="button" className="circle theme-toggle" onClick={toggle}
            aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
            title={dark ? "Switch to light mode" : "Switch to dark mode"}>
      {dark ? <SunIcon size={18} /> : <MoonIcon size={18} />}
    </button>
  );
}

// The non-diagnostic statement is part of the frame (Shell.jsx renders it on
// every screen, sign-in included), so no screen can render without it.
export function Banner() {
  return (
    <div className="banner" role="note" aria-label="Non-diagnostic notice">
      <span className="dot" aria-hidden="true" />
      NON-DIAGNOSTIC. DECISION SUPPORT ONLY.
    </div>
  );
}
