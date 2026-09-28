import { useEffect, useState } from "react";

const CLINICAL_TEMPLATES = {
  MR_TUMOR: [
    "Enhancing tumor margin expansion",
    "Central necrotic core involvement",
    "Peritumoral vasogenic edema boundary",
    "Suspected satellite lesion",
    "Review for surgical resection boundary",
    "Mass effect on lateral ventricle",
  ],
  MR_ALZHEIMER: [
    "Bilateral hippocampal volume reduction",
    "Temporal horn enlargement",
    "Cortical sulcal widening",
    "Normal age-matched baseline",
    "Recommend follow-up volumetric study",
  ],
  CT: [
    "Hyperdense acute hemorrhage focus",
    "Midline shift evaluation required",
    "Subdural collection margin",
    "Bone window inspection recommended",
    "No acute intracranial abnormality",
  ],
  CXR: [
    "Discrete pulmonary nodule focus",
    "Perihilar airspace opacity",
    "Pleural effusion blunting costophrenic angle",
    "Cardiomegaly index > 0.50",
    "Clear lung fields bilaterally",
  ],
};

export default function NoteEditorModal({
  isOpen,
  initialData,
  onSave,
  onCancel,
  busy = false,
}) {
  if (!isOpen || !initialData) return null;

  const [text, setText] = useState(initialData.note_text || "");
  const [region, setRegion] = useState(initialData.segmentation_region || "");

  const isMri = initialData.modality === "MR" || initialData.coordinate_space === "NIFTI_WORLD";
  const isAlz = isMri && (initialData.segmentation_region?.includes("T1") || initialData.study_id?.includes("alz"));
  const isCt = initialData.modality === "CT";
  const isCxr = initialData.modality === "CR" || initialData.modality === "DX";

  const templateCategory = isAlz ? "MR_ALZHEIMER" : isMri ? "MR_TUMOR" : isCt ? "CT" : "CXR";
  const templates = CLINICAL_TEMPLATES[templateCategory] || CLINICAL_TEMPLATES.MR_TUMOR;

  // Keyboard shortcut listener (Ctrl+Enter to save, Esc to cancel)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        if (text.trim() && !busy) {
          onSave({
            ...initialData,
            note_text: text.trim(),
            segmentation_region: region || initialData.segmentation_region || null,
          });
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [text, region, busy, initialData, onSave, onCancel]);

  const handleSave = (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    onSave({
      ...initialData,
      note_text: text.trim(),
      segmentation_region: region || initialData.segmentation_region || null,
    });
  };

  const handleAddTemplate = (tmpl) => {
    setText((prev) => {
      const trimmed = prev.trim();
      return trimmed ? `${trimmed}. ${tmpl}` : tmpl;
    });
  };

  return (
    <div className="note-editor-overlay" role="dialog" aria-modal="true">
      <div className="note-editor-card">
        <div className="note-editor-header">
          <div className="header-title-group">
            <span className="editor-icon">📍</span>
            <h3 className="editor-title">
              {initialData.id ? "Edit Clinician Pinpoint Note" : "New Clinician Pinpoint Note"}
            </h3>
          </div>
          <button
            type="button"
            className="btn-modal-close"
            onClick={onCancel}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Spatial Anchoring Metadata HUD */}
        <div className="note-spatial-hud">
          <div className="spatial-hud-row">
            <span className="hud-label">Coordinate Space:</span>
            <span className="hud-val mono bold">{initialData.coordinate_space || "IMAGE_NORMALIZED"}</span>
          </div>

          {isMri && initialData.world_mm && (
            <div className="spatial-hud-row">
              <span className="hud-label">World Stereotactic:</span>
              <span className="hud-val mono text-accent">
                X: {Number(initialData.world_mm.x).toFixed(1)} mm, Y: {Number(initialData.world_mm.y).toFixed(1)} mm, Z: {Number(initialData.world_mm.z).toFixed(1)} mm
              </span>
            </div>
          )}

          {isMri && initialData.voxel && (
            <div className="spatial-hud-row">
              <span className="hud-label">Voxel Index:</span>
              <span className="hud-val mono">
                [{Math.round(initialData.voxel.x)}, {Math.round(initialData.voxel.y)}, {Math.round(initialData.voxel.z)}]
              </span>
            </div>
          )}

          {/* MRI notes carry voxel indices in coordinate_x/y, shown above; not fractions. */}
          {!isMri && (isCxr || isCt || initialData.coordinate_x != null) && (
            <div className="spatial-hud-row">
              <span className="hud-label">Image Normalized Coords:</span>
              <span className="hud-val mono">
                X: {(Number(initialData.coordinate_x || 0) * 100).toFixed(1)}%, Y: {(Number(initialData.coordinate_y || 0) * 100).toFixed(1)}%
                {initialData.slice_index != null && ` (Slice: ${initialData.slice_index + 1})`}
              </span>
            </div>
          )}

          {initialData.segmentation_region && (
            <div className="spatial-hud-row">
              <span className="hud-label">Segmentation Region:</span>
              <span className={`hud-region-badge region-${String(initialData.segmentation_region).toLowerCase().replace(/[^a-z0-9]/g, "-")}`}>
                {initialData.segmentation_region}
              </span>
            </div>
          )}
        </div>

        {/* Quick Clinical Template Chips */}
        <div className="editor-quick-templates">
          <span className="quick-templates-label">Quick Clinical Findings:</span>
          <div className="template-chips-row">
            {templates.map((tmpl) => (
              <button
                key={tmpl}
                type="button"
                className="btn-template-chip"
                onClick={() => handleAddTemplate(tmpl)}
                title="Click to insert template into note text"
              >
                + {tmpl}
              </button>
            ))}
          </div>
        </div>

        <form onSubmit={handleSave} className="note-editor-form">
          <label className="editor-input-label">
            <span>Clinical Findings / Radiologist Note:</span>
            <textarea
              className="note-textarea"
              rows={4}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Enter clinical observations, lesion review note, surgical planning comments... (Ctrl+Enter to save)"
              autoFocus
              required
            />
          </label>

          <div className="note-editor-actions">
            <span className="editor-shortcut-hint mono">Press Ctrl+Enter to save • Esc to cancel</span>
            <button
              type="button"
              className="btn-action-secondary"
              onClick={onCancel}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-action-primary"
              disabled={busy || !text.trim()}
            >
              {busy ? "Saving Note..." : initialData.id ? "Update Note" : "Save Pinpoint Note"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
