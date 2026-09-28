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
    setStatus(saveSettings(next) ? "Saved in this browser." : "This browser does not allow saving; the setting lasts until reload.");
    if (onChange) onChange(next);
  };

  return (
    <div className="settings-view" data-testid="settings-view">
      <div className="settings-header">
        <h2 className="center-title">Settings</h2>
        <p className="center-subtitle">Kept in this browser only.</p>
      </div>
      <div className="settings-form">
        <div className="settings-card">
          <div className="settings-row">
            <div>
              <span className="setting-label">First MR sequence in the 3D viewer</span>
              <span className="setting-desc">The sequence NiiVue opens a brain MR study with.</span>
            </div>
            <select value={settings.mrSequence} onChange={(e) => update("mrSequence", e.target.value)}
                    className="settings-select" aria-label="First MR sequence">
              {MR_SEQUENCES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </div>
          <div className="settings-row">
            <div>
              <span className="setting-label">Worklist refresh</span>
              <span className="setting-desc">How often the worklist asks the API for new studies.</span>
            </div>
            <select value={settings.refreshSeconds} onChange={(e) => update("refreshSeconds", Number(e.target.value))}
                    className="settings-select" aria-label="Worklist refresh">
              {REFRESH_CHOICES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </div>
          <div className="settings-row">
            <div>
              <span className="setting-label">Light or dark</span>
              <span className="setting-desc">Also in the header.</span>
            </div>
            <ThemeToggle />
          </div>
        </div>
        {status && <p className="note" role="status">{status}</p>}
      </div>
    </div>
  );
}
