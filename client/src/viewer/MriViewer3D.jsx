import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { loadSettings, MR_SEQUENCES } from "../settings.js";

/**
 * MriViewer3D: multi-planar and 3D volume view of a brain MR study, with NiiVue.
 * The volumes are the model's own NIfTI inputs and its segmentation, stored as
 * evidence at ingest. The API hands out a short-lived presigned URL for each
 * (S3 on AWS, a signed /api/blob URL locally); NiiVue fetches it directly.
 * Volumes shown are the brain model's own measurements (adapters/brats.py).
 */
export default function MriViewer3D({ studyId, token, onUnavailable }) {
  const [sequence, setSequence] = useState(() => loadSettings().mrSequence);
  const [showSeg, setShowSeg] = useState(true);
  const [opacity, setOpacity] = useState(0.6);
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

  useEffect(() => {
    let active = true;
    api.metrics(token, studyId).then((d) => active && setMetrics(d)).catch(() => {});
    return () => { active = false; };
  }, [studyId, token]);

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
        if (!cancelled) setError("The 3D viewer library did not load. Reload the page.");
        return;
      }

      let volumes;
      try {
        const vol = await api.volume(token, studyId, sequence);
        volumes = [{ url: vol.url, name: vol.name, colormap: "gray", opacity: 1.0 }];
        if (showSeg) {
          const seg = await api.segmentation(token, studyId).catch(() => null);
          if (seg) volumes.push({ url: seg.url, name: seg.name, colormap: "red", opacity });
        }
      } catch (e) {
        if (!cancelled) {
          setError(`No 3D volume for this study: ${e.message}`);
          setLoading(false);
          if (onUnavailable) onUnavailable();
        }
        return;
      }
      const fallbackVol = volumes.slice(0, 1);

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
            if (nvAxialRef.current) await nvAxialRef.current.loadVolumes(fallbackVol);
            if (nvCoronalRef.current) await nvCoronalRef.current.loadVolumes(fallbackVol);
            if (nvSagittalRef.current) await nvSagittalRef.current.loadVolumes(fallbackVol);
            if (nv3DRef.current) await nv3DRef.current.loadVolumes(fallbackVol);
          } catch (e2) {
            console.warn("Fallback load:", e2);
            setError(`Could not load the volumes: ${e2.message || e2}`);
            if (onUnavailable) onUnavailable();
          }
          setLoading(false);
        }
      }
    }

    initAndLoad();

    return () => {
      cancelled = true;
    };
  }, [studyId, sequence, viewLayout, token]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="mri-3d-workstation" data-testid="mri-3d-workstation">
      {/* Top Clinical MPR Workstation Toolbar */}
      <div className="mri-toolbar">
        <div className="toolbar-group">
          <span className="toolbar-label">Sequence:</span>
          <div className="segmented-group" role="group" aria-label="MR sequence">
            {MR_SEQUENCES.map(([id, label]) => (
              <button key={id} type="button"
                      className={`segmented-btn ${sequence === id ? "active" : ""}`}
                      onClick={() => setSequence(id)}>{label}</button>
            ))}
          </div>
        </div>

        {(
          <div className="toolbar-group segmentation-controls">
            <span className="toolbar-label">Model segmentation:</span>
            <button
              type="button"
              className={`btn-toggle ${showSeg ? "active" : ""}`}
              onClick={() => setShowSeg((prev) => !prev)}
              aria-pressed={showSeg}
              title="The brain model's segmentation (MONAI SegResNet)"
            >
              <span className="status-indicator-dot"></span>
              {showSeg ? "Mask: shown" : "Mask: hidden"}
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
          <span>Loading the volumes.</span>
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
              <span className="badge-name">3D volume</span>
              <span className="badge-coords mono">Az: 120° El: 25°</span>
            </div>
            <div className="raymarch-hint">Drag to rotate, wheel to zoom</div>
            <canvas ref={canvas3DRef} className="mri-canvas canvas-3d" />
          </div>
        )}
      </div>

      {metrics?.volumes_cm3 && (
        <div className="mri-metrics-bar" data-testid="mri-volumes">
          <div className="metrics-group">
            <span className="metrics-bar-label">Model volumes:</span>
            {[["whole_tumour", "Whole tumour", "wt"], ["tumour_core", "Tumour core", "tc"],
              ["enhancing", "Enhancing", "et"], ["edema", "Edema", "wt"]].map(([k, label, dot]) => (
              <div key={k} className={`metric-chip chip-${dot}`}>
                <span className={`metric-dot dot-${dot}`}></span>
                <span className="metric-title">{label}:</span>
                <span className="metric-val mono">{Number(metrics.volumes_cm3[k]).toFixed(2)} cm3</span>
              </div>
            ))}
          </div>
          <span className="note">{metrics.basis}</span>
        </div>
      )}
    </div>
  );
}
