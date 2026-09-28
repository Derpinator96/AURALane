import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

/**
 * MriViewer3D: Advanced 3D Multi-Planar Reconstruction (MPR) & Raymarching Viewer
 * Powered by NiiVue (WebGL 2.0).
 * Displays Axial, Coronal, Sagittal, and 3D Volume rendering with interactive
 * sequence selection, segmentation mask overlays, and volumetric metrics.
 */
function getSegmentationRegionLabel(values, isAlzheimer) {
  if (isAlzheimer) {
    return "User annotation on T1 volume";
  }
  if (!values || values.length < 2) {
    return "Unsegmented location";
  }
  const segVal = Math.round(Number(values[1]) || 0);
  if (segVal === 4 || segVal === 3) {
    return "ET (Enhancing Tumor)";
  } else if (segVal === 1) {
    return "TC (Tumor Core)";
  } else if (segVal === 2) {
    return "WT (Whole Tumor)";
  } else {
    return "Unsegmented location";
  }
}

/**
 * Interactive Pinpoint Spatial Dot Marker with Depth Awareness & Quick Actions
 */
function MriPinMarker({
  ann,
  index,
  xPercent,
  yPercent,
  sliceDelta = null,
  isSelected,
  onSelect,
  onEdit,
  onDelete,
}) {
  const [hovered, setHovered] = useState(false);
  const region = ann.segmentation_region || "User note";
  const noteText = ann.note_text || "";
  const author = ann.created_by || "Clinician";

  // Slice proximity styling (exact slice, nearby, or distant)
  const isClose = sliceDelta == null || Math.abs(sliceDelta) <= 3;
  const isMid = sliceDelta != null && Math.abs(sliceDelta) > 3 && Math.abs(sliceDelta) <= 12;

  const opacityStyle = isSelected || hovered || isClose ? 1.0 : isMid ? 0.45 : 0.2;
  const scaleStyle = isSelected ? 1.3 : isClose ? 1.0 : 0.85;

  const isTop = yPercent < 45;
  const isLeft = xPercent < 28;
  const isRight = xPercent > 72;

  let posClass = isTop ? "popover-below" : "popover-above";
  if (isLeft) posClass += " popover-align-left";
  else if (isRight) posClass += " popover-align-right";

  return (
    <div
      className={`mri-pin-marker ${isSelected ? "selected" : ""} ${isClose ? "in-slice" : "out-slice"}`}
      style={{
        left: `${Math.max(4, Math.min(96, xPercent))}%`,
        top: `${Math.max(4, Math.min(96, yPercent))}%`,
        opacity: opacityStyle,
        transform: `translate(-50%, -50%) scale(${scaleStyle})`,
      }}
      onClick={(e) => {
        e.stopPropagation();
        onSelect?.(ann);
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={`Note #${index + 1}: ${noteText} ${sliceDelta != null && Math.abs(sliceDelta) > 0 ? `(${Math.abs(sliceDelta)} slices ${sliceDelta > 0 ? "below" : "above"})` : ""}`}
    >
      {isClose && <div className="mri-pin-pulse"></div>}
      <div className="mri-pin-core">
        <span className="mri-pin-number">{index + 1}</span>
      </div>

      {hovered && (
        <div className={`mri-pin-popover ${posClass}`} onClick={(e) => e.stopPropagation()}>
          <div className="mri-pin-popover-header">
            <span className="popover-tag">Note #{index + 1}</span>
            {region && <span className="popover-region-badge">{region}</span>}
          </div>
          <div className="popover-note-text">{noteText}</div>
          <div className="popover-meta mono">
            <span>By: {author.split("@")[0]}</span>
            {ann.voxel && (
              <span>
                [{Math.round(ann.voxel.x)}, {Math.round(ann.voxel.y)}, {Math.round(ann.voxel.z)}]
              </span>
            )}
          </div>
          {(onEdit || onDelete) && (
            <div className="popover-actions-bar">
              <button
                type="button"
                className="btn-popover-action btn-popover-focus"
                onClick={() => onSelect?.(ann)}
              >
                Focus
              </button>
              {onEdit && (
                <button
                  type="button"
                  className="btn-popover-action"
                  onClick={() => onEdit?.(ann)}
                >
                  Edit
                </button>
              )}
              {onDelete && (
                <button
                  type="button"
                  className="btn-popover-action btn-popover-delete"
                  onClick={() => onDelete?.(ann.id || ann.annotation_id)}
                >
                  Delete
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function MriViewer3D({
  studyId,
  initialSequence = "t1ce",
  isAlzheimer = false,
  annotations = [],
  selectedAnnotation = null,
  onSelectAnnotation = null,
  onEditAnnotation = null,
  onDeleteAnnotation = null,
  onRequestNewNote = null,
  isAddNoteMode = false,
  onToggleAddNoteMode = null,
}) {
  const isAlz = isAlzheimer || (studyId && studyId.toLowerCase().includes("alz"));
  const [sequence, setSequence] = useState(isAlz ? "t1" : initialSequence);
  const [showSeg, setShowSeg] = useState(!isAlz);
  const [opacity, setOpacity] = useState(0.7);
  const [metrics, setMetrics] = useState(null);
  const [viewLayout, setViewLayout] = useState("mpr"); // 'mpr' | '3d' | 'axial'
  const [showCrosshairs, setShowCrosshairs] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentVoxel, setCurrentVoxel] = useState(null);

  const canvasAxialRef = useRef(null);
  const canvasCoronalRef = useRef(null);
  const canvasSagittalRef = useRef(null);
  const canvas3DRef = useRef(null);

  const nvAxialRef = useRef(null);
  const nvCoronalRef = useRef(null);
  const nvSagittalRef = useRef(null);
  const nv3DRef = useRef(null);

  const lastLocationRef = useRef(null);

  // Global keyboard shortcuts: 'N' to toggle Add Note mode, 'Esc' to cancel
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
      if (e.key === "n" || e.key === "N") {
        if (!e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault();
          onToggleAddNoteMode?.();
        }
      } else if (e.key === "Escape" && isAddNoteMode) {
        e.preventDefault();
        onToggleAddNoteMode?.();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isAddNoteMode, onToggleAddNoteMode]);

  // Synchronize crosshair position to selected annotation's 3D voxel
  useEffect(() => {
    if (!selectedAnnotation || !selectedAnnotation.voxel) return;
    const { x, y, z } = selectedAnnotation.voxel;
    [nvAxialRef.current, nvCoronalRef.current, nvSagittalRef.current, nv3DRef.current].forEach((nv) => {
      if (nv && nv.vox2frac) {
        try {
          const frac = nv.vox2frac([Number(x), Number(y), Number(z)]);
          if (frac && frac.length === 3) {
            if (nv.setCrosshairPos) nv.setCrosshairPos(frac[0], frac[1], frac[2]);
            else if (nv.scene) nv.scene.crosshairPos = frac;
            if (nv.drawScene) nv.drawScene();
          }
        } catch (e) {
          console.warn("Crosshair sync error:", e);
        }
      }
    });
  }, [selectedAnnotation]);

  // Fetch quantitative volumetric metrics (tumor studies)
  useEffect(() => {
    if (isAlz) return;
    let active = true;
    fetch(`/api/studies/${encodeURIComponent(studyId)}/metrics`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data) setMetrics(data);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [studyId, isAlz]);

  // Handle Opacity Changes Dynamically without reloading full volume
  useEffect(() => {
    [nvAxialRef.current, nvCoronalRef.current, nvSagittalRef.current, nv3DRef.current].forEach((nv) => {
      if (nv && nv.volumes && nv.volumes.length > 1) {
        nv.setOpacity(1, showSeg ? opacity : 0.0);
        if (nv.updateGLVolume) nv.updateGLVolume();
        if (nv.drawScene) nv.drawScene();
      }
    });
  }, [opacity, showSeg]);

  // Handle Crosshair toggle
  const toggleCrosshairs = () => {
    const nextVal = !showCrosshairs;
    setShowCrosshairs(nextVal);
    [nvAxialRef.current, nvCoronalRef.current, nvSagittalRef.current].forEach((nv) => {
      if (nv && nv.opts) {
        nv.opts.crosshairColor = nextVal ? [1, 0, 0, 0.7] : [0, 0, 0, 0];
        if (nv.drawScene) nv.drawScene();
      }
    });
  };

  // Reset Scene views
  const resetViews = () => {
    [nvAxialRef.current, nvCoronalRef.current, nvSagittalRef.current].forEach((nv) => {
      if (nv && nv.resetScene) nv.resetScene();
    });
    if (nv3DRef.current && nv3DRef.current.setRenderAzimuthElevation) {
      nv3DRef.current.setRenderAzimuthElevation(120, 25);
      if (nv3DRef.current.drawScene) nv3DRef.current.drawScene();
    }
  };

  // Handle canvas click to place pinpoint note
  const handleViewportClick = (planeName, e) => {
    if (!isAddNoteMode && e.type !== "contextmenu") return;
    if (e.type === "contextmenu") e.preventDefault();

    const loc = lastLocationRef.current;
    if (!loc || !loc.vox || !loc.mm) return;

    const [vx, vy, vz] = loc.vox;
    const [mx, my, mz] = loc.mm;
    const region = getSegmentationRegionLabel(loc.values, isAlz);

    onRequestNewNote?.({
      modality: "MR",
      coordinate_space: "NIFTI_WORLD",
      voxel: { x: vx, y: vy, z: vz },
      world_mm: { x: mx, y: my, z: mz },
      coordinate_x: vx,
      coordinate_y: vy,
      coordinate_z: vz,
      slice_index: vz,
      segmentation_region: region,
      viewer_context: {
        sequence,
        plane: planeName,
        layout: viewLayout,
      },
    });
  };

  const setupLocationCallback = (nv, planeName) => {
    nv.onLocationChange = (data) => {
      lastLocationRef.current = data;
      if (data && data.vox) {
        setCurrentVoxel({
          vox: data.vox,
          mm: data.mm,
          region: getSegmentationRegionLabel(data.values, isAlz),
        });
      }
    };
  };

  // Initialize and load NiiVue viewports
  useEffect(() => {
    let cancelled = false;

    async function initAndLoad() {
      setLoading(true);
      setError(null);

      // Wait a tick for DOM canvases to mount
      await new Promise((r) => setTimeout(r, 60));

      const Niivue = window.niivue?.Niivue || window.Niivue;
      if (!Niivue) {
        if (!cancelled) setError("3D Medical Engine (NiiVue) initializing. Please reload if persistent.");
        return;
      }

      const seqFileName = sequence.endsWith(".nii") || sequence.endsWith(".nii.gz") ? sequence : `${sequence}.nii`;
      const volumeUrl = api.volumeUrl(studyId, seqFileName);
      const segUrl = showSeg && !isAlz ? `${api.segmentationUrl(studyId)}.nii` : null;

      const volumes = [{ url: volumeUrl, name: seqFileName, colormap: "gray", opacity: 1.0 }];
      if (segUrl) {
        volumes.push({ url: segUrl, name: "final_seg.nii", colormap: "red", opacity: opacity });
      }

      try {
        // 1. Axial (SliceType 0)
        if (canvasAxialRef.current && (viewLayout === "mpr" || viewLayout === "axial")) {
          if (!nvAxialRef.current) {
            nvAxialRef.current = new Niivue({ isColorbar: false, backColor: [0.03, 0.04, 0.07, 1.0] });
            nvAxialRef.current.attachToCanvas(canvasAxialRef.current);
          }
          setupLocationCallback(nvAxialRef.current, "Axial");
          if (nvAxialRef.current.setSliceType) nvAxialRef.current.setSliceType(0);
          await nvAxialRef.current.loadVolumes(volumes);
        }

        // 2. Coronal (SliceType 1)
        if (canvasCoronalRef.current && viewLayout === "mpr") {
          if (!nvCoronalRef.current) {
            nvCoronalRef.current = new Niivue({ isColorbar: false, backColor: [0.03, 0.04, 0.07, 1.0] });
            nvCoronalRef.current.attachToCanvas(canvasCoronalRef.current);
          }
          setupLocationCallback(nvCoronalRef.current, "Coronal");
          if (nvCoronalRef.current.setSliceType) nvCoronalRef.current.setSliceType(1);
          await nvCoronalRef.current.loadVolumes(volumes);
        }

        // 3. Sagittal (SliceType 2)
        if (canvasSagittalRef.current && viewLayout === "mpr") {
          if (!nvSagittalRef.current) {
            nvSagittalRef.current = new Niivue({ isColorbar: false, backColor: [0.03, 0.04, 0.07, 1.0] });
            nvSagittalRef.current.attachToCanvas(canvasSagittalRef.current);
          }
          setupLocationCallback(nvSagittalRef.current, "Sagittal");
          if (nvSagittalRef.current.setSliceType) nvSagittalRef.current.setSliceType(2);
          await nvSagittalRef.current.loadVolumes(volumes);
        }

        // 4. 3D Volume Raymarch (SliceType 4)
        if (canvas3DRef.current && (viewLayout === "mpr" || viewLayout === "3d")) {
          if (!nv3DRef.current) {
            nv3DRef.current = new Niivue({ isColorbar: false, backColor: [0.02, 0.02, 0.04, 1.0] });
            nv3DRef.current.attachToCanvas(canvas3DRef.current);
          }
          setupLocationCallback(nv3DRef.current, "3D");
          if (nv3DRef.current.setSliceType) nv3DRef.current.setSliceType(4);
          await nv3DRef.current.loadVolumes(volumes);
          if (nv3DRef.current.setRenderAzimuthElevation) {
            nv3DRef.current.setRenderAzimuthElevation(120, 25);
          }
          if (nv3DRef.current.drawScene) {
            nv3DRef.current.drawScene();
          }
        }

        if (!cancelled) setLoading(false);
      } catch (err) {
        if (!cancelled) {
          console.warn("NiiVue volume loading notice:", err);
          try {
            const fallbackVol = [{ url: volumeUrl, name: seqFileName, colormap: "gray", opacity: 1.0 }];
            if (nvAxialRef.current) await nvAxialRef.current.loadVolumes(fallbackVol);
            if (nvCoronalRef.current) await nvCoronalRef.current.loadVolumes(fallbackVol);
            if (nvSagittalRef.current) await nvSagittalRef.current.loadVolumes(fallbackVol);
            if (nv3DRef.current) await nv3DRef.current.loadVolumes(fallbackVol);
          } catch (e2) {
            console.warn("Fallback load:", e2);
          }
          setLoading(false);
        }
      }
    }

    initAndLoad();

    return () => {
      cancelled = true;
    };
  }, [studyId, sequence, viewLayout]);

  return (
    <div className={`mri-3d-workstation ${isAddNoteMode ? "pinpoint-active-mode" : ""}`} data-testid="mri-3d-workstation">
      {/* Top Clinical MPR Workstation Toolbar */}
      <div className="mri-toolbar">
        {isAlz ? (
          <div className="toolbar-group">
            <span className="toolbar-label">MR Modality:</span>
            <div className="segmented-group">
              <span className="segmented-btn active" style={{ cursor: "default" }}>
                T1 3D Structural (Cognitive Triage Pipeline)
              </span>
            </div>
          </div>
        ) : (
          <div className="toolbar-group">
            <span className="toolbar-label">Sequence:</span>
            <div className="segmented-group" role="group" aria-label="MRI Sequence Channels">
              {[
                { id: "t1ce", label: "T1c (ch0)", desc: "Contrast-Enhanced Tumor" },
                { id: "t1", label: "T1 (ch1)", desc: "Native Anatomy" },
                { id: "t2", label: "T2 (ch2)", desc: "Edema & Water" },
                { id: "flair", label: "FLAIR (ch3)", desc: "Peritumoral Boundary" },
              ].map((s) => (
                <button
                  key={s.id}
                  type="button"
                  title={s.desc}
                  className={`segmented-btn ${sequence === s.id ? "active" : ""}`}
                  onClick={() => setSequence(s.id)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {!isAlz && (
          <div className="toolbar-group segmentation-controls">
            <span className="toolbar-label">AI Segmentation:</span>
            <button
              type="button"
              className={`btn-toggle ${showSeg ? "active" : ""}`}
              onClick={() => setShowSeg((prev) => !prev)}
              aria-pressed={showSeg}
              title="Toggle 3D MONAI SegResNet Tumor Mask"
            >
              <span className="status-indicator-dot"></span>
              {showSeg ? "Mask: ACTIVE" : "Mask: HIDDEN"}
            </button>
            {showSeg && (
              <label className="slider-label">
                <span>Opacity: {Math.round(opacity * 100)}%</span>
                <input
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value={opacity}
                  onChange={(e) => setOpacity(parseFloat(e.target.value))}
                  className="opacity-slider"
                  aria-label="Mask Opacity"
                />
              </label>
            )}
          </div>
        )}

        {/* Viewport Layout Switcher */}
        <div className="toolbar-group layout-toggle">
          <span className="toolbar-label">Layout:</span>
          <div className="segmented-group">
            <button
              type="button"
              className={`segmented-btn ${viewLayout === "mpr" ? "active" : ""}`}
              onClick={() => setViewLayout("mpr")}
              title="4-View Multi-Planar Reconstruction"
            >
              4-View MPR
            </button>
            <button
              type="button"
              className={`segmented-btn ${viewLayout === "3d" ? "active" : ""}`}
              onClick={() => setViewLayout("3d")}
              title="Full 3D Volume Raymarch Focus"
            >
              3D Raymarch
            </button>
            <button
              type="button"
              className={`segmented-btn ${viewLayout === "axial" ? "active" : ""}`}
              onClick={() => setViewLayout("axial")}
              title="Axial Focus"
            >
              Axial Focus
            </button>
          </div>
        </div>

        {/* Pinpoint & Utility Actions */}
        <div className="toolbar-group tool-actions">
          {onToggleAddNoteMode && (
            <button
              type="button"
              className={`btn-tool-action btn-pin-mode ${isAddNoteMode ? "active" : ""}`}
              onClick={onToggleAddNoteMode}
              title="Click anywhere on the image to drop a spatially anchored note"
            >
              📍 {isAddNoteMode ? "Pin Active" : "Add Note"}
            </button>
          )}
          <button
            type="button"
            className={`btn-tool-action ${showCrosshairs ? "active" : ""}`}
            onClick={toggleCrosshairs}
            title="Toggle Orthogonal Sync Crosshairs"
          >
            Crosshairs
          </button>
          <button
            type="button"
            className="btn-tool-action"
            onClick={resetViews}
            title="Reset Camera Angles & Zoom"
          >
            Reset
          </button>
        </div>
      </div>

      {isAddNoteMode && (
        <div className="mri-pin-instruction-hud">
          <span className="pulse-dot"></span>
          <span>
            <strong>Pinpoint Mode Active:</strong> Click any region on the Axial, Coronal, Sagittal, or 3D view to place a clinician note.
            {currentVoxel && (
              <span className="voxel-preview mono">
                {" "}[Vox: {currentVoxel.vox?.join(", ")} | Region: {currentVoxel.region}]
              </span>
            )}
          </span>
        </div>
      )}

      {loading && (
        <div className="mri-loading-indicator">
          <div className="spinner"></div>
          <span>Rendering 3D Multi-Planar Orthogonal Slices & Volume Shaders...</span>
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}

      {/* Viewport Grid */}
      <div
        className={`mri-grid ${
          viewLayout === "3d"
            ? "layout-single-3d"
            : viewLayout === "axial"
            ? "layout-single-axial"
            : "layout-mpr-grid"
        }`}
      >
        {(viewLayout === "mpr" || viewLayout === "axial") && (
          <div className="viewport-cell cell-axial">
            <div className="viewport-badge">
              <span className="badge-name">Axial (Transverse)</span>
              <span className="badge-coords mono">Z-Axis</span>
            </div>
            <div className="orientation-tag top-tag">A</div>
            <div className="orientation-tag bottom-tag">P</div>
            <div className="orientation-tag left-tag">R</div>
            <div className="orientation-tag right-tag">L</div>
            <div className="mri-canvas-wrapper">
              <canvas
                ref={canvasAxialRef}
                className="mri-canvas"
                onClick={(e) => handleViewportClick("Axial", e)}
                onContextMenu={(e) => handleViewportClick("Axial", e)}
              />
              <div className="mri-pin-dot-overlay">
                {annotations.map((ann, idx) => {
                  const vx = Number(ann.voxel?.x ?? ann.coordinate_x ?? 0);
                  const vy = Number(ann.voxel?.y ?? ann.coordinate_y ?? 0);
                  const vz = Number(ann.voxel?.z ?? ann.coordinate_z ?? 0);
                  const volDims = nvAxialRef.current?.volumes?.[0]?.hdr?.dims || nvAxialRef.current?.volumes?.[0]?.dims || [1, 240, 240, 155];
                  const dimX = volDims[1] || 240;
                  const dimY = volDims[2] || 240;
                  const xPct = (vx / dimX) * 100;
                  const yPct = ((dimY - vy) / dimY) * 100;
                  const curZ = currentVoxel?.vox?.[2] ?? 75;
                  const isSelected = selectedAnnotation?.id === ann.id || selectedAnnotation?.annotation_id === ann.annotation_id;
                  return (
                    <MriPinMarker
                      key={ann.id || ann.annotation_id || idx}
                      ann={ann}
                      index={idx}
                      xPercent={xPct}
                      yPercent={yPct}
                      sliceDelta={vz - curZ}
                      isSelected={isSelected}
                      onSelect={onSelectAnnotation}
                      onEdit={onEditAnnotation}
                      onDelete={onDeleteAnnotation}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {viewLayout === "mpr" && (
          <>
            <div className="viewport-cell cell-coronal">
              <div className="viewport-badge">
                <span className="badge-name">Coronal (Frontal)</span>
                <span className="badge-coords mono">Y-Axis</span>
              </div>
              <div className="orientation-tag top-tag">S</div>
              <div className="orientation-tag bottom-tag">I</div>
              <div className="orientation-tag left-tag">R</div>
              <div className="orientation-tag right-tag">L</div>
              <div className="mri-canvas-wrapper">
                <canvas
                  ref={canvasCoronalRef}
                  className="mri-canvas"
                  onClick={(e) => handleViewportClick("Coronal", e)}
                  onContextMenu={(e) => handleViewportClick("Coronal", e)}
                />
                <div className="mri-pin-dot-overlay">
                  {annotations.map((ann, idx) => {
                    const vx = Number(ann.voxel?.x ?? ann.coordinate_x ?? 0);
                    const vy = Number(ann.voxel?.y ?? ann.coordinate_y ?? 0);
                    const vz = Number(ann.voxel?.z ?? ann.coordinate_z ?? 0);
                    const volDims = nvCoronalRef.current?.volumes?.[0]?.hdr?.dims || nvCoronalRef.current?.volumes?.[0]?.dims || [1, 240, 240, 155];
                    const dimX = volDims[1] || 240;
                    const dimZ = volDims[3] || 155;
                    const xPct = (vx / dimX) * 100;
                    const yPct = ((dimZ - vz) / dimZ) * 100;
                    const curY = currentVoxel?.vox?.[1] ?? 120;
                    const isSelected = selectedAnnotation?.id === ann.id || selectedAnnotation?.annotation_id === ann.annotation_id;
                    return (
                      <MriPinMarker
                        key={ann.id || ann.annotation_id || idx}
                        ann={ann}
                        index={idx}
                        xPercent={xPct}
                        yPercent={yPct}
                        sliceDelta={vy - curY}
                        isSelected={isSelected}
                        onSelect={onSelectAnnotation}
                        onEdit={onEditAnnotation}
                        onDelete={onDeleteAnnotation}
                      />
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="viewport-cell cell-sagittal">
              <div className="viewport-badge">
                <span className="badge-name">Sagittal (Lateral)</span>
                <span className="badge-coords mono">X-Axis</span>
              </div>
              <div className="orientation-tag top-tag">S</div>
              <div className="orientation-tag bottom-tag">I</div>
              <div className="orientation-tag left-tag">A</div>
              <div className="orientation-tag right-tag">P</div>
              <div className="mri-canvas-wrapper">
                <canvas
                  ref={canvasSagittalRef}
                  className="mri-canvas"
                  onClick={(e) => handleViewportClick("Sagittal", e)}
                  onContextMenu={(e) => handleViewportClick("Sagittal", e)}
                />
                <div className="mri-pin-dot-overlay">
                  {annotations.map((ann, idx) => {
                    const vx = Number(ann.voxel?.x ?? ann.coordinate_x ?? 0);
                    const vy = Number(ann.voxel?.y ?? ann.coordinate_y ?? 0);
                    const vz = Number(ann.voxel?.z ?? ann.coordinate_z ?? 0);
                    const volDims = nvSagittalRef.current?.volumes?.[0]?.hdr?.dims || nvSagittalRef.current?.volumes?.[0]?.dims || [1, 240, 240, 155];
                    const dimY = volDims[2] || 240;
                    const dimZ = volDims[3] || 155;
                    const xPct = (vy / dimY) * 100;
                    const yPct = ((dimZ - vz) / dimZ) * 100;
                    const curX = currentVoxel?.vox?.[0] ?? 120;
                    const isSelected = selectedAnnotation?.id === ann.id || selectedAnnotation?.annotation_id === ann.annotation_id;
                    return (
                      <MriPinMarker
                        key={ann.id || ann.annotation_id || idx}
                        ann={ann}
                        index={idx}
                        xPercent={xPct}
                        yPercent={yPct}
                        sliceDelta={vx - curX}
                        isSelected={isSelected}
                        onSelect={onSelectAnnotation}
                        onEdit={onEditAnnotation}
                        onDelete={onDeleteAnnotation}
                      />
                    );
                  })}
                </div>
              </div>
            </div>
          </>
        )}

        {(viewLayout === "mpr" || viewLayout === "3d") && (
          <div className="viewport-cell cell-3d">
            <div className="viewport-badge">
              <span className="badge-name">3D Volume Raymarching (Interactive 360°)</span>
              <span className="badge-coords mono">Az: 120° El: 25°</span>
            </div>
            <div className="raymarch-hint">Drag to Rotate • Wheel to Zoom</div>
            <div className="mri-canvas-wrapper">
              <canvas
                ref={canvas3DRef}
                className="mri-canvas canvas-3d"
                onClick={(e) => handleViewportClick("3D", e)}
                onContextMenu={(e) => handleViewportClick("3D", e)}
              />
              <div className="mri-pin-dot-overlay">
                {annotations.map((ann, idx) => {
                  const vx = Number(ann.voxel?.x ?? ann.coordinate_x ?? 0);
                  const vz = Number(ann.voxel?.z ?? ann.coordinate_z ?? 0);
                  const volDims = nv3DRef.current?.volumes?.[0]?.hdr?.dims || nv3DRef.current?.volumes?.[0]?.dims || [1, 240, 240, 155];
                  const dimX = volDims[1] || 240;
                  const dimZ = volDims[3] || 155;
                  const xPct = (vx / dimX) * 100;
                  const yPct = ((dimZ - vz) / dimZ) * 100;
                  const isSelected = selectedAnnotation?.id === ann.id || selectedAnnotation?.annotation_id === ann.annotation_id;
                  return (
                    <MriPinMarker
                      key={ann.id || ann.annotation_id || idx}
                      ann={ann}
                      index={idx}
                      xPercent={xPct}
                      yPercent={yPct}
                      sliceDelta={null}
                      isSelected={isSelected}
                      onSelect={onSelectAnnotation}
                      onEdit={onEditAnnotation}
                      onDelete={onDeleteAnnotation}
                    />
                  );
                })}
              </div>
              {annotations.length > 0 && (
                <div className="mri-3d-pin-floating-hud">
                  <span>3D Notes:</span>
                  <div className="hud-pin-dot-list">
                    {annotations.map((ann, idx) => {
                      const isSelected = selectedAnnotation?.id === ann.id || selectedAnnotation?.annotation_id === ann.annotation_id;
                      return (
                        <button
                          key={ann.id || ann.annotation_id || idx}
                          type="button"
                          className={`hud-pin-pill ${isSelected ? "active" : ""}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectAnnotation?.(ann);
                          }}
                          title={`Focus Note #${idx + 1}: ${ann.note_text}`}
                        >
                          {idx + 1}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>


      {/* Quantitative Volumetric Measurements HUD Footer */}
      {metrics && !isAlz && (
        <div className="mri-metrics-bar">
          <div className="metrics-group">
            <span className="metrics-bar-label">AI Volumetrics:</span>
            <div className="metric-chip chip-wt" title="Whole Tumor Volume (Edema + Core + Enhancing)">
              <span className="metric-dot dot-wt"></span>
              <span className="metric-title">Whole Tumor (WT):</span>
              <span className="metric-val mono">{metrics.wt_volume_cm3?.toFixed(2)} cm³</span>
            </div>
            <div className="metric-chip chip-tc" title="Tumor Core Volume (Necrotic + Enhancing)">
              <span className="metric-dot dot-tc"></span>
              <span className="metric-title">Tumor Core (TC):</span>
              <span className="metric-val mono">{metrics.tc_volume_cm3?.toFixed(2)} cm³</span>
            </div>
            <div className="metric-chip chip-et" title="Active Enhancing Tumor Volume">
              <span className="metric-dot dot-et"></span>
              <span className="metric-title">Enhancing (ET):</span>
              <span className="metric-val mono">{metrics.et_volume_cm3?.toFixed(2)} cm³</span>
            </div>
          </div>

          {metrics.centroid_world_mm && (
            <div className="metric-chip chip-centroid" title="Stereotactic World Coordinates">
              <span className="metric-title">Centroid:</span>
              <span className="metric-val mono">
                [{metrics.centroid_world_mm.map((c) => Math.round(c)).join(", ")}] mm
              </span>
            </div>
          )}

          {metrics.dice_validation && (
            <div className="metric-chip validation" title="Ground Truth Validation Dice Overlap">
              <span className="metric-title">Dice Overlap:</span>
              <span className="metric-val mono">
                WT: {metrics.dice_validation.WT_dice} • TC: {metrics.dice_validation.TC_dice} • ET: {metrics.dice_validation.ET_dice}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
