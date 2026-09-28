import { useState } from "react";

export default function SettingsView() {
  const [defaultSeq, setDefaultSeq] = useState("t1ce");
  const [audioAlerts, setAudioAlerts] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState("30");
  const [saved, setSaved] = useState(false);

  const handleSave = (e) => {
    e.preventDefault();
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <div className="settings-view" data-testid="settings-view">
      <div className="settings-header">
        <h2 className="center-title">Clinician Workstation Settings</h2>
        <p className="center-subtitle">
          Configure local reading preferences, notification thresholds, and PACS ingestion parameters
        </p>
      </div>

      <form onSubmit={handleSave} className="settings-form">
        <div className="settings-card">
          <h3 className="card-section-title">Imaging & Viewer Defaults</h3>
          <div className="settings-row">
            <div>
              <span className="setting-label">Default Brain Tumor MRI Sequence:</span>
              <span className="setting-desc">Initial sequence loaded into the 3D multi-planar workstation</span>
            </div>
            <select
              value={defaultSeq}
              onChange={(e) => setDefaultSeq(e.target.value)}
              className="settings-select"
            >
              <option value="t1ce">T1 Contrast-Enhanced (T1c)</option>
              <option value="t1">T1 Native</option>
              <option value="t2">T2 Weighted</option>
              <option value="flair">FLAIR</option>
            </select>
          </div>

          <div className="settings-row">
            <div>
              <span className="setting-label">Worklist Polling Rate:</span>
              <span className="setting-desc">Interval to check for newly triaged studies from AWS pipeline</span>
            </div>
            <select
              value={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.value)}
              className="settings-select"
            >
              <option value="15">Every 15 seconds</option>
              <option value="30">Every 30 seconds</option>
              <option value="60">Every 60 seconds</option>
              <option value="0">Manual refresh only</option>
            </select>
          </div>
        </div>

        <div className="settings-card">
          <h3 className="card-section-title">Critical Alerts & Audio</h3>
          <div className="settings-row">
            <div>
              <span className="setting-label">Critical Case Audio Chime:</span>
              <span className="setting-desc">Play distinct auditory tone when a CRITICAL study (&lt;15 min SLA) enters queue</span>
            </div>
            <input
              type="checkbox"
              checked={audioAlerts}
              onChange={(e) => setAudioAlerts(e.target.checked)}
              className="settings-checkbox"
            />
          </div>
        </div>

        <div className="settings-card">
          <h3 className="card-section-title">PACS Node Configuration (DICOM C-STORE / DIMSE)</h3>
          <div className="pacs-grid">
            <label className="pacs-field">
              <span>Local AE Title:</span>
              <input type="text" defaultValue="AURALANE_WL" className="pacs-input mono" />
            </label>
            <label className="pacs-field">
              <span>DICOM Port:</span>
              <input type="text" defaultValue="11112" className="pacs-input mono" />
            </label>
            <label className="pacs-field">
              <span>Hospital PACS Host:</span>
              <input type="text" defaultValue="pacs.hospital.internal" className="pacs-input mono" />
            </label>
          </div>
        </div>

        <div className="settings-actions">
          {saved && <span className="save-toast">Preferences saved to workstation profile</span>}
          <button type="submit" className="btn-primary">
            Save Preferences
          </button>
        </div>
      </form>
    </div>
  );
}
