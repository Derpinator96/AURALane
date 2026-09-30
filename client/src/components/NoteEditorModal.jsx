import { useEffect, useState } from "react";
import { Overlay } from "./ui.jsx";

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

// The editor mounts fresh each time it opens, so its text starts from the note being
// edited and no hook runs conditionally.
export default function NoteEditorModal(props) {
  if (!props.isOpen || !props.initialData) return null;
  return <NoteEditorForm {...props} />;
}

function NoteEditorForm({ initialData, onSave, onCancel, busy = false }) {
  const [text, setText] = useState(initialData.note_text || "");
  const [region] = useState(initialData.segmentation_region || "");

  const isMri = initialData.modality === "MR" || initialData.coordinate_space === "NIFTI_WORLD";
  const isAlz = isMri && (initialData.segmentation_region?.includes("T1") || initialData.study_id?.includes("alz"));
  const isCt = initialData.modality === "CT";
  const isCxr = initialData.modality === "CR" || initialData.modality === "DX";

  const templateCategory = isAlz ? "MR_ALZHEIMER" : isMri ? "MR_TUMOR" : isCt ? "CT" : "CXR";
  const templates = CLINICAL_TEMPLATES[templateCategory] || CLINICAL_TEMPLATES.MR_TUMOR;

  const submit = () => {
    if (!text.trim() || busy) return;
    onSave({
      ...initialData,
      note_text: text.trim(),
      segmentation_region: region || initialData.segmentation_region || null,
    });
  };

  // Ctrl+Enter saves, Esc cancels.
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  const handleAddTemplate = (tmpl) => {
    setText((prev) => {
      const trimmed = prev.trim();
      return trimmed ? `${trimmed}. ${tmpl}` : tmpl;
    });
  };

  return (
    <Overlay onClose={onCancel}>
      <form className="modal-card" role="dialog" aria-modal="true" aria-label="Note"
            onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="modal-header">
          <div>
            <h2 className="modal-title">{initialData.id ? "Edit note" : "New note"}</h2>
            <div className="crumbs">Notes <span aria-hidden="true">›</span> <strong>{initialData.id ? "Edit" : "New"}</strong></div>
          </div>
          <div className="modal-actions">
            <button type="button" className="pill pill-quiet" onClick={onCancel} disabled={busy}>Cancel</button>
            <button type="submit" className="pill pill-primary" disabled={busy || !text.trim()}>
              {busy ? "Saving" : initialData.id ? "Update note" : "Save note"}
            </button>
          </div>
        </div>

        {/* Where the note is anchored. Only what the viewer recorded. */}
        <div className="ct-chips note-anchor">
          <span className="chip chip-quiet">{initialData.coordinate_space || "IMAGE_NORMALIZED"}</span>
          {isMri && initialData.world_mm && (
            <span className="chip chip-quiet">
              X {Number(initialData.world_mm.x).toFixed(1)} mm, Y {Number(initialData.world_mm.y).toFixed(1)} mm, Z {Number(initialData.world_mm.z).toFixed(1)} mm
            </span>
          )}
          {isMri && initialData.voxel && (
            <span className="chip chip-quiet">
              Voxel {Math.round(initialData.voxel.x)}, {Math.round(initialData.voxel.y)}, {Math.round(initialData.voxel.z)}
            </span>
          )}
          {!isMri && (isCxr || isCt || initialData.coordinate_x != null) && (
            <span className="chip chip-quiet">
              X {(Number(initialData.coordinate_x || 0) * 100).toFixed(1)}%, Y {(Number(initialData.coordinate_y || 0) * 100).toFixed(1)}%
              {initialData.slice_index != null && `, slice ${initialData.slice_index + 1}`}
            </span>
          )}
          {initialData.segmentation_region && <span className="chip">{initialData.segmentation_region}</span>}
        </div>

        <label className="field-label">Note
          <textarea className="note-textarea" rows={5} value={text} onChange={(e) => setText(e.target.value)}
                    placeholder="Clinical observation" autoFocus required />
        </label>

        <div className="template-chips-row" aria-label="Quick findings">
          {templates.map((tmpl) => (
            <button key={tmpl} type="button" className="pill pill-sm pill-quiet" onClick={() => handleAddTemplate(tmpl)}
                    title="Add to the note">+ {tmpl}</button>
          ))}
        </div>
      </form>
    </Overlay>
  );
}
