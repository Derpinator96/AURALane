import { useState } from "react";
import { timeUTC } from "../worklist.js";
import { CloseIcon } from "./Icons.jsx";

export default function AnnotationsPanel({
  annotations = [],
  activeAnnotationId = null,
  onSelectAnnotation,
  onEditAnnotation,
  onDeleteAnnotation,
  isAddNoteMode = false,
  onToggleAddNoteMode,
}) {
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  const formatCoords = (ann) => {
    if (ann.world_mm) {
      const { x, y, z } = ann.world_mm;
      return `[${Number(x).toFixed(1)}, ${Number(y).toFixed(1)}, ${Number(z).toFixed(1)}] mm`;
    }
    if (ann.voxel) {
      const { x, y, z } = ann.voxel;
      return `vox [${Math.round(x)}, ${Math.round(y)}, ${Math.round(z)}]`;
    }
    if (ann.coordinate_x != null && ann.coordinate_y != null) {
      return `norm (${(ann.coordinate_x * 100).toFixed(0)}%, ${(ann.coordinate_y * 100).toFixed(0)}%)`;
    }
    return "Anchored";
  };

  return (
    <div className="study-annotations-card" data-testid="annotations-panel">
      <div className="annotations-header">
        <div className="annotations-title-group">
          <h4 className="card-section-title">Notes</h4>
          <span className="annotations-count-badge mono">
            {annotations.length}
          </span>
        </div>
        <button
          type="button"
          className={`btn-add-pinpoint ${isAddNoteMode ? "active" : ""}`}
          onClick={onToggleAddNoteMode}
          title={isAddNoteMode ? "Click the image to drop a note" : "Add a note"}
        >
          {isAddNoteMode ? "Cancel" : "Add note"}
        </button>
      </div>

      {annotations.length === 0 ? (
        <p className="note text-faint">No notes yet.</p>
      ) : (
        <div className="annotations-list">
          {annotations.map((ann) => {
            const isSelected = ann.id === activeAnnotationId;
            const isDeleting = confirmDeleteId === ann.id;

            return (
              <div
                key={ann.id || ann.annotation_id}
                className={`annotation-item-card ${isSelected ? "selected" : ""}`}
                onClick={() => onSelectAnnotation && onSelectAnnotation(ann)}
              >
                <div className="ann-card-header">
                  <div className="ann-meta-tags">
                    {ann.segmentation_region && (
                      <span className={`ann-region-pill region-${String(ann.segmentation_region).toLowerCase().replace(/[^a-z0-9]/g, "-")}`}>
                        {ann.segmentation_region}
                      </span>
                    )}
                    <span className="ann-coords-tag mono" title="Spatial anchor coordinates">
                      {formatCoords(ann)}
                    </span>
                  </div>

                  <div className="ann-card-actions" onClick={(e) => e.stopPropagation()}>
                    <button
                      type="button"
                      className="btn-ann-action"
                      onClick={() => onEditAnnotation(ann)}
                      title="Edit note text"
                    >
                      Edit
                    </button>
                    {isDeleting ? (
                      <div className="delete-confirm-group">
                        <button
                          type="button"
                          className="btn-ann-action delete-confirm"
                          onClick={() => {
                            onDeleteAnnotation(ann.id || ann.annotation_id);
                            setConfirmDeleteId(null);
                          }}
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          className="btn-ann-action delete-cancel"
                          onClick={() => setConfirmDeleteId(null)}
                        >
                          <CloseIcon size={13} />
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="btn-ann-action delete-btn"
                        onClick={() => setConfirmDeleteId(ann.id || ann.annotation_id)}
                        title="Delete note"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>

                <p className="ann-text-body">{ann.note_text}</p>

                <div className="ann-footer-row">
                  <span className="ann-author mono text-faint">
                    {ann.created_by || "radiologist"}
                  </span>
                  <span className="ann-timestamp mono text-faint">
                    {ann.created_at ? `${timeUTC(ann.created_at)} UTC` : "--"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
