import { useState } from "react";
import { ThemeToggle } from "../Chrome.jsx";
import { loadSettings, MR_SEQUENCES, REFRESH_CHOICES, saveSettings } from "../settings.js";

// Only settings that take effect. Kept in this browser, not on the server.
export default function SettingsView({ onChange }) {
  const [settings, setSettings] = useState(loadSettings);
  const [status, setStatus] = useState(null);

  const update = (key, value) => {
    const next = { ...settings, [key]: value };
    setSettings(next);
    setStatus(saveSettings(next) ? "Saved" : "Not saved: this browser does not allow it");
    if (onChange) onChange(next);
  };

  return (
    <section className="panel settings-card" data-testid="settings-view" aria-label="Settings">
      <div className="settings-row">
        <span className="setting-label">First MR sequence in the 3D viewer</span>
        <select value={settings.mrSequence} onChange={(e) => update("mrSequence", e.target.value)}
                className="settings-select" aria-label="First MR sequence">
          {MR_SEQUENCES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </div>
      <div className="settings-row">
        <span className="setting-label">Worklist refresh</span>
        <select value={settings.refreshSeconds} onChange={(e) => update("refreshSeconds", Number(e.target.value))}
                className="settings-select" aria-label="Worklist refresh">
          {REFRESH_CHOICES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
      </div>
      <div className="settings-row">
        <span className="setting-label">Light or dark</span>
        <ThemeToggle />
      </div>
      {status && <p className="chip chip-quiet settings-status" role="status"><span className="dot" style={{ "--dot": "var(--ok)" }} />{status}</p>}
    </section>
  );
}
