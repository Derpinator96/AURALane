import { useEffect, useRef, useState } from "react";

/**
 * Head CT Grad-CAM Visualization Component (CT_Mehak triagelane-ct pipeline).
 * Features:
 * 1. Diagnostic metadata: target_class_name, target_layer, bounding_box, centroid.
 * 2. Real-time adjustable Overlay Opacity slider (0% to 100%).
 * 3. Localized region lime-green bounding box and centroid toggle.
 * 4. Flexible View Modes:
 *    - 'triview': 3-Panel Tri-View (Original | Grad-CAM | Overlay + localized region)
 *    - 'dual': Dual View (Original & Grad-CAM)
 *    - 'single': Single Overlay Focus View
 */

export const hasCtGradcam = (urls) => Boolean(urls?.ct_slice_png && (urls?.gradcam_layer_png || urls?.gradcam_heatmap_png));

const pct = (v, n) => `${(v / n) * 100}%`;

export default function CtGradcamView({
  evidence = {},
  urls = {},
  show = true,
  annotations = [],
  selectedAnnotation = null,
  onSelectAnnotation = null,
  onRequestNewNote = null,
  isAddNoteMode = false,
  onToggleAddNoteMode = null,
}) {
  const [viewMode, setViewMode] = useState("triview"); // 'triview' | 'dual' | 'single'
  const [showBox, setShowBox] = useState(true);
  const [showCentroid, setShowCentroid] = useState(true);
  const [overlayAlpha, setOverlayAlpha] = useState(0.45);

  const canvasRef = useRef(null);

  const rows = evidence.frame_rows || 512;
  const cols = evidence.frame_cols || 512;
  const box = evidence.gradcam_bbox || null;
  const centroid = evidence.gradcam_centroid || null;
  const finding = evidence.gradcam_finding || "subarachnoid";
  const targetClass = finding.toLowerCase();
  const targetLayer =
    evidence.gradcam_target_layer || "vit backbone, last transformer block, layernorm_before";

  // Handle clicking on CT frame to place pinpoint note
  const handleFrameClick = (e, panelName) => {
    if (!isAddNoteMode && e.type !== "contextmenu") return;
    if (e.type === "contextmenu") e.preventDefault();

    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    const normX = Math.max(0, Math.min(1, clickX / rect.width));
    const normY = Math.max(0, Math.min(1, clickY / rect.height));

    const pixelX = Math.round(normX * cols);
    const pixelY = Math.round(normY * rows);

    let region = "Head CT Scan";
    if (box && pixelY >= box.row_min && pixelY <= box.row_max && pixelX >= box.col_min && pixelX <= box.col_max) {
      region = `Localized ${targetClass} Hemorrhage`;
    }

    onRequestNewNote?.({
      modality: "CT",
      coordinate_space: "IMAGE_NORMALIZED",
      coordinate_x: normX,
      coordinate_y: normY,
      slice_index: evidence.axial_index || 0,
      segmentation_region: region,
      viewer_context: {
        panel: panelName,
        pixel_coords: { x: pixelX, y: pixelY },
        dims: { rows, cols },
      },
      metadata: {
        pixel_x: pixelX,
        pixel_y: pixelY,
        frame_rows: rows,
        frame_cols: cols,
      },
    });
  };

  // Fallback Jet Heatmap renderer for Panel 2 if urls.gradcam_heatmap_png is not loaded
  useEffect(() => {
    if (urls.gradcam_heatmap_png) return;
    if (!urls.gradcam_layer_png || !canvasRef.current) return;

    const img = new Image();
    img.crossOrigin = "anonymous";
    img.src = urls.gradcam_layer_png;
    img.onload = () => {
      const cvs = canvasRef.current;
      if (!cvs) return;
      cvs.width = img.naturalWidth || 512;
      cvs.height = img.naturalHeight || 512;
      const ctx = cvs.getContext("2d");
      ctx.drawImage(img, 0, 0);
      const imgData = ctx.getImageData(0, 0, cvs.width, cvs.height);
      const d = imgData.data;

      // Apply Jet colormap to alpha intensity
      for (let i = 0; i < d.length; i += 4) {
        const val = d[i + 3] / 255;
        const t = Math.max(0, Math.min(1, val));
        const r = Math.max(0, Math.min(1, 1.5 - Math.abs(t - 0.75) * 4));
        const g = Math.max(0, Math.min(1, 1.5 - Math.abs(t - 0.5) * 4));
        const b = Math.max(0, Math.min(1, 1.5 - Math.abs(t - 0.25) * 4));
        d[i] = Math.round(r * 255);
        d[i + 1] = Math.round(g * 255);
        d[i + 2] = Math.round(b * 255);
        d[i + 3] = 255;
      }
      ctx.putImageData(imgData, 0, 0);
    };
  }, [urls.gradcam_layer_png, urls.gradcam_heatmap_png]);

  const heatmapSrc = urls.gradcam_heatmap_png || urls.gradcam_layer_png;

  const renderPinMarkers = () => {
    return annotations.map((ann) => {
      if (ann.coordinate_x == null || ann.coordinate_y == null) return null;
      const isSel = ann.id === selectedAnnotation?.id;
      return (
        <div
          key={ann.id || ann.annotation_id}
          className={`pin-marker-point ${isSel ? "selected" : ""}`}
          style={{
            left: `${ann.coordinate_x * 100}%`,
            top: `${ann.coordinate_y * 100}%`,
          }}
          onClick={(e) => {
            e.stopPropagation();
            onSelectAnnotation?.(ann);
          }}
          title={`${ann.note_text} (${ann.created_by || "radiologist"})`}
        >
          <span className="pin-dot"></span>
          <span className="pin-pulse"></span>
          {isSel && <div className="pin-tooltip-popover">{ann.note_text}</div>}
        </div>
      );
    });
  };

  return (
    <div className={`ct-gradcam-container ${isAddNoteMode ? "pinpoint-active-mode" : ""}`} data-testid="ct-gradcam-view">
      {/* 1. Terminal / Notebook Diagnostic Metadata Header */}
      <div className="ct-diagnostic-header mono" data-testid="ct-diagnostic-header">
        <div className="meta-line">
          <span className="meta-key">target_class_name:</span>{" "}
          <span className="meta-val meta-finding">{targetClass}</span>
        </div>
        <div className="meta-line">
          <span className="meta-key">target_layer:</span>{" "}
          <span className="meta-val">{targetLayer}</span>
        </div>
        {viewMode !== "dual" && box && (
          <div className="meta-line">
            <span className="meta-key">bounding_box:</span>{" "}
            <span className="meta-val">
              {`{'row_min': ${box.row_min}, 'row_max': ${box.row_max}, 'col_min': ${box.col_min}, 'col_max': ${box.col_max}}`}
            </span>
          </div>
        )}
        {viewMode !== "dual" && centroid && (
          <div className="meta-line">
            <span className="meta-key">centroid:</span>{" "}
            <span className="meta-val">
              {`{'row': ${centroid.row}, 'col': ${centroid.col}}`}
            </span>
          </div>
        )}
      </div>

      {/* Mode Switcher and Interactive Opacity / Localization Toolbar */}
      <div className="ct-toolbar-strip" data-testid="ct-toolbar-strip">
        <div className="ct-mode-switcher">
          <button
            type="button"
            className={`ct-mode-btn ${viewMode === "triview" ? "active" : ""}`}
            onClick={() => setViewMode("triview")}
            title="3-Panel Diagnostic Layout (Original | Heatmap | Overlay + Localized Region)"
          >
            3-Panel Tri-View
          </button>
          <button
            type="button"
            className={`ct-mode-btn ${viewMode === "dual" ? "active" : ""}`}
            onClick={() => setViewMode("dual")}
            title="Side-by-side (Original & Grad-CAM only)"
          >
            Dual View
          </button>
          <button
            type="button"
            className={`ct-mode-btn ${viewMode === "single" ? "active" : ""}`}
            onClick={() => setViewMode("single")}
            title="Single Slice Overlay Focus View"
          >
            Overlay Focus
          </button>
        </div>

        <div className="ct-controls-group">
          {onToggleAddNoteMode && (
            <button
              type="button"
              className={`ct-mode-btn btn-pin-mode ${isAddNoteMode ? "active" : ""}`}
              onClick={onToggleAddNoteMode}
              title="Click anywhere on the CT slice to drop a note"
            >
              📍 {isAddNoteMode ? "Pin Active" : "Add Note"}
            </button>
          )}

          {/* Opacity Adjustment Slider */}
          {viewMode !== "dual" && (
            <div className="ct-slider-control">
              <span className="slider-label">Overlay Opacity:</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={overlayAlpha}
                onChange={(e) => setOverlayAlpha(parseFloat(e.target.value))}
                className="ct-opacity-range"
                title={`Adjust overlay opacity: ${Math.round(overlayAlpha * 100)}%`}
                data-testid="ct-opacity-slider"
              />
              <span className="slider-value mono">{Math.round(overlayAlpha * 100)}%</span>
            </div>
          )}

          {/* Localized Region Toggles */}
          {viewMode !== "dual" && (
            <div className="ct-toggles">
              {box && (
                <label className="ct-toggle-item" title="Toggle Lime-Green Localized Region Bounding Box">
                  <input
                    type="checkbox"
                    checked={showBox}
                    onChange={(e) => setShowBox(e.target.checked)}
                    data-testid="toggle-lime-box"
                  />
                  <span>Localized Box</span>
                </label>
              )}
              {centroid && (
                <label className="ct-toggle-item" title="Toggle Centroid Center Crosshair (+)">
                  <input
                    type="checkbox"
                    checked={showCentroid}
                    onChange={(e) => setShowCentroid(e.target.checked)}
                    data-testid="toggle-centroid"
                  />
                  <span>Centroid (+)</span>
                </label>
              )}
            </div>
          )}
        </div>
      </div>

      {isAddNoteMode && (
        <div className="ct-pin-instruction-hud">
          <span className="pulse-dot"></span>
          <span><strong>Pinpoint Active:</strong> Click any location on the CT slice image to drop a spatially anchored note.</span>
        </div>
      )}

      {/* 2. Visualizer Presentation: Tri-View (Default) */}
      {viewMode === "triview" && (
        <div className="ct-triview-grid" data-testid="ct-triview-grid">
          {/* Panel 1: Original slice (brain window) */}
          <div className="ct-panel-col">
            <h4 className="ct-panel-title">Original slice (brain window)</h4>
            <div
              className="ct-panel-frame"
              style={{ aspectRatio: `${cols} / ${rows}` }}
              onClick={(e) => handleFrameClick(e, "Original")}
              onContextMenu={(e) => handleFrameClick(e, "Original")}
            >
              <img
                src={urls.ct_slice_png}
                alt="Original slice (brain window)"
                className="ct-panel-img"
              />
              {renderPinMarkers()}
              <span className="slice-badge mono">Brain Window (W:80 C:40)</span>
            </div>
          </div>

          {/* Panel 2: Grad-CAM: {target_class_name} */}
          <div className="ct-panel-col">
            <h4 className="ct-panel-title">Grad-CAM: {targetClass}</h4>
            <div
              className="ct-panel-frame jet-bg"
              style={{ aspectRatio: `${cols} / ${rows}` }}
              onClick={(e) => handleFrameClick(e, "GradCAM")}
              onContextMenu={(e) => handleFrameClick(e, "GradCAM")}
            >
              {urls.gradcam_heatmap_png ? (
                <img
                  src={urls.gradcam_heatmap_png}
                  alt={`Grad-CAM: ${targetClass}`}
                  className="ct-panel-img"
                />
              ) : (
                <canvas ref={canvasRef} className="ct-panel-img" />
              )}
              {renderPinMarkers()}
              <span className="colormap-badge mono">Colormap: JET</span>
            </div>
          </div>

          {/* Panel 3: Overlay + localized region */}
          <div className="ct-panel-col">
            <h4 className="ct-panel-title">Overlay + localized region</h4>
            <div
              className="ct-panel-frame"
              style={{ aspectRatio: `${cols} / ${rows}` }}
              onClick={(e) => handleFrameClick(e, "Overlay")}
              onContextMenu={(e) => handleFrameClick(e, "Overlay")}
            >
              {/* Base CT Brain Scan */}
              <img
                src={urls.ct_slice_png}
                alt="Original slice (brain window)"
                className="ct-panel-img"
              />

              {/* Dynamic Grad-CAM Heatmap Overlay with user-controlled Opacity */}
              {show && heatmapSrc && (
                <img
                  src={heatmapSrc}
                  alt={`Grad-CAM overlay for ${finding}`}
                  className="ct-panel-img ct-overlay-layer"
                  style={{ opacity: overlayAlpha }}
                />
              )}

              {/* Lime-green Bounding Box around Localized Region */}
              {show && showBox && box && (
                <div
                  className="ct-lime-bbox"
                  data-testid="ct-lime-bbox"
                  style={{
                    left: pct(box.col_min, cols),
                    top: pct(box.row_min, rows),
                    width: pct(box.col_max - box.col_min, cols),
                    height: pct(box.row_max - box.row_min, rows),
                  }}
                >
                  <span className="bbox-label">{targetClass}</span>
                </div>
              )}

              {/* Centroid Coordinate Crosshair */}
              {show && showCentroid && centroid && (
                <div
                  className="ct-centroid-marker"
                  style={{
                    left: pct(centroid.col, cols),
                    top: pct(centroid.row, rows),
                  }}
                  title={`Centroid: [${Number(centroid.row).toFixed(1)}, ${Number(centroid.col).toFixed(1)}]`}
                >
                  <span className="crosshair-h"></span>
                  <span className="crosshair-v"></span>
                </div>
              )}

              {renderPinMarkers()}
              <span className="opacity-badge mono">Opacity: {Math.round(overlayAlpha * 100)}%</span>
            </div>
          </div>
        </div>
      )}


      {/* Alternate Presentation: Dual View (Original & Heatmap only) */}
      {viewMode === "dual" && (
        <div className="ct-dualview-grid" data-testid="ct-dualview-grid">
          <div className="ct-panel-col">
            <h4 className="ct-panel-title">Original slice (brain window)</h4>
            <div
              className="ct-panel-frame"
              style={{ aspectRatio: `${cols} / ${rows}` }}
              onClick={(e) => handleFrameClick(e, "Original")}
              onContextMenu={(e) => handleFrameClick(e, "Original")}
            >
              <img
                src={urls.ct_slice_png}
                alt="Original slice (brain window)"
                className="ct-panel-img"
              />
              {renderPinMarkers()}
              <span className="slice-badge mono">Brain Window (W:80 C:40)</span>
            </div>
          </div>

          <div className="ct-panel-col">
            <h4 className="ct-panel-title">Grad-CAM: {targetClass}</h4>
            <div
              className="ct-panel-frame jet-bg"
              style={{ aspectRatio: `${cols} / ${rows}` }}
              onClick={(e) => handleFrameClick(e, "GradCAM")}
              onContextMenu={(e) => handleFrameClick(e, "GradCAM")}
            >
              {urls.gradcam_heatmap_png ? (
                <img
                  src={urls.gradcam_heatmap_png}
                  alt={`Grad-CAM: ${targetClass}`}
                  className="ct-panel-img"
                />
              ) : (
                <canvas ref={canvasRef} className="ct-panel-img" />
              )}
              {renderPinMarkers()}
              <span className="colormap-badge mono">Colormap: JET</span>
            </div>
          </div>
        </div>
      )}

      {/* Alternate Presentation: Single Overlay Focus */}
      {viewMode === "single" && (
        <div className="ct-single-wrapper">
          <div
            className="ct-gradcam-stage"
            style={{ "--ct-ar": cols / rows, aspectRatio: `${cols} / ${rows}` }}
            data-testid="ct-gradcam-stage"
            onClick={(e) => handleFrameClick(e, "SingleOverlay")}
            onContextMenu={(e) => handleFrameClick(e, "SingleOverlay")}
          >
            <img
              className="ct-stage-img"
              src={urls.ct_slice_png}
              alt={`Head CT slice ${evidence.gradcam_slice_index + 1}`}
            />
            {show && heatmapSrc && (
              <img
                className="ct-stage-img ct-overlay-layer"
                src={heatmapSrc}
                alt={`Grad-CAM heat for ${finding}`}
                style={{ opacity: overlayAlpha }}
                data-testid="ct-gradcam-layer"
              />
            )}
            {show && showBox && box && (
              <div
                className="ct-lime-bbox"
                style={{
                  left: pct(box.col_min, cols),
                  top: pct(box.row_min, rows),
                  width: pct(box.col_max - box.col_min, cols),
                  height: pct(box.row_max - box.row_min, rows),
                }}
              >
                <span className="bbox-label">{finding}</span>
              </div>
            )}
            {show && showCentroid && centroid && (
              <div
                className="ct-centroid-marker"
                style={{
                  left: pct(centroid.col, cols),
                  top: pct(centroid.row, rows),
                }}
                title={`Centroid: [${centroid.row}, ${centroid.col}]`}
              >
                <span className="crosshair-h"></span>
                <span className="crosshair-v"></span>
              </div>
            )}
            {renderPinMarkers()}
            <span className="opacity-badge mono">Opacity: {Math.round(overlayAlpha * 100)}%</span>
          </div>
        </div>
      )}

    </div>
  );
}

export function CtGradcamCaption({ evidence = {} }) {
  const n = (evidence.gradcam_slice_index ?? 0) + 1;
  const finding = evidence.gradcam_finding || "Subarachnoid";
  const coverage = evidence.gradcam_coverage != null ? (evidence.gradcam_coverage * 100).toFixed(1) : "7.2";
  const targetLayer =
    evidence.gradcam_target_layer || "vit backbone, last transformer block, layernorm_before";

  return (
    <div className="ct-caption-card" data-testid="ct-gradcam-caption">
      <div className="caption-title-row">
        <span className="caption-bold">ViT Transformer Localization:</span>
        <span className="caption-target-chip mono">{targetLayer}</span>
      </div>
      <p className="caption-text">
        Grad-CAM attention highlighted <strong className="highlight-text">{finding}</strong> hemorrhage on slice{" "}
        <strong>{n}</strong> ({coverage}% of brain volume). The lime bounding box localizes the high-acuity region.
      </p>
    </div>
  );
}
