import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

/**
 * MriViewer3D: Advanced 3D Multi-Planar Reconstruction (MPR) & Raymarching Viewer
 * Powered by NiiVue (WebGL 2.0).
 * Displays Axial, Coronal, Sagittal, and 3D Volume rendering with interactive
 * sequence selection, segmentation mask overlays, and volumetric metrics.
 */
export default function MriViewer3D({ studyId, initialSequence = "t1ce", isAlzheimer = false }) {
  const isAlz = isAlzheimer || (studyId && studyId.toLowerCase().includes("alz"));
  const [sequence, setSequence] = useState(isAlz ? "t1" : initialSequence);
  const [showSeg, setShowSeg] = useState(!isAlz);
  const [opacity, setOpacity] = useState(0.7);
  const [metrics, setMetrics] = useState(null);
  const [viewLayout, setViewLayout] = useState("mpr"); // 'mpr' | '3d' | 'axial'
  const [showCrosshairs, setShowCrosshairs] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const canvasAxialRef = useRef(null);
  const canvasCoronalRef = useRef(null);
  const canvasSagittalRef = useRef(null);
  const canvas3DRef = useRef(null);

  const nvAxialRef = useRef(null);
  const nvCoronalRef = useRef(null);
  const nvSagittalRef = useRef(null);
  const nv3DRef = useRef(null);

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
          if (nvAxialRef.current.setSliceType) nvAxialRef.current.setSliceType(0);
          await nvAxialRef.current.loadVolumes(volumes);
        }

        // 2. Coronal (SliceType 1)
        if (canvasCoronalRef.current && viewLayout === "mpr") {
          if (!nvCoronalRef.current) {
            nvCoronalRef.current = new Niivue({ isColorbar: false, backColor: [0.03, 0.04, 0.07, 1.0] });
            nvCoronalRef.current.attachToCanvas(canvasCoronalRef.current);
          }
          if (nvCoronalRef.current.setSliceType) nvCoronalRef.current.setSliceType(1);
          await nvCoronalRef.current.loadVolumes(volumes);
        }

        // 3. Sagittal (SliceType 2)
        if (canvasSagittalRef.current && viewLayout === "mpr") {
          if (!nvSagittalRef.current) {
            nvSagittalRef.current = new Niivue({ isColorbar: false, backColor: [0.03, 0.04, 0.07, 1.0] });
            nvSagittalRef.current.attachToCanvas(canvasSagittalRef.current);
          }
          if (nvSagittalRef.current.setSliceType) nvSagittalRef.current.setSliceType(2);
          await nvSagittalRef.current.loadVolumes(volumes);
        }

        // 4. 3D Volume Raymarch (SliceType 4)
        if (canvas3DRef.current && (viewLayout === "mpr" || viewLayout === "3d")) {
          if (!nv3DRef.current) {
            nv3DRef.current = new Niivue({ isColorbar: false, backColor: [0.02, 0.02, 0.04, 1.0] });
            nv3DRef.current.attachToCanvas(canvas3DRef.current);
          }
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
          // Fallback load without segmentation if seg fails
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
    <div className="mri-3d-workstation" data-testid="mri-3d-workstation">
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

        {/* Utility Actions */}
        <div className="toolbar-group tool-actions">
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
            <canvas ref={canvasAxialRef} className="mri-canvas" />
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
              <canvas ref={canvasCoronalRef} className="mri-canvas" />
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
              <canvas ref={canvasSagittalRef} className="mri-canvas" />
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
            <canvas ref={canvas3DRef} className="mri-canvas canvas-3d" />
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
