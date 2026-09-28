import { useState } from "react";

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

  const handleSave = (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    onSave({
      ...initialData,
      note_text: text.trim(),
      segmentation_region: region || initialData.segmentation_region || null,
    });
  };

  const isMri = initialData.modality === "MR" || initialData.coordinate_space === "NIFTI_WORLD";
  const isCt = initialData.modality === "CT";
  const isCxr = initialData.modality === "CR" || initialData.modality === "DX";

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

          {(isCxr || isCt || initialData.coordinate_x != null) && (
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

        <form onSubmit={handleSave} className="note-editor-form">
          <label className="editor-input-label">
            <span>Clinical Findings / Radiologist Note:</span>
            <textarea
              className="note-textarea"
              rows={4}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Enter clinical observations, lesion review note, surgical planning comments..."
              autoFocus
              required
            />
          </label>

          <div className="note-editor-actions">
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
