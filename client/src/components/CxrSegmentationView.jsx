import { useEffect, useRef, useState, useMemo } from "react";

export const hasCxrSegmentation = (urls) => Boolean(urls?.cxr_segmentation_layer_png || urls?.cxr_segmentation_composite_png);

/**
 * 14 PSPNet Anatomical Targets and Colors derived from shaurya-webapp:
 * 0: Left Clavicle (Cyan)
 * 1: Right Clavicle (Orange)
 * 2: Left Scapula (Magenta)
 * 3: Right Scapula (Deep Pink)
 * 4: Left Lung (Deep Sky Blue)
 * 5: Right Lung (Dodger Blue)
 * 6: Left Hilus Pulmonis (Blue Violet)
 * 7: Right Hilus Pulmonis (Medium Purple)
 * 8: Heart (Red-Orange)
 * 9: Aorta (Gold)
 * 10: Facies Diaphragmatica (Lime Green)
 * 11: Mediastinum (Medium Spring Green)
 * 12: Weasand / Trachea (Crimson)
 * 13: Spine (Lawn Green)
 */
export const DEFAULT_CXR_REGIONS = [
  { id: 0, raw_name: "Left Clavicle", name: "Left Clavicle", system: "Musculoskeletal", color_hex: "#00ffff", color_rgb: [0, 255, 255], coverage_pct: 0.86 },
  { id: 1, raw_name: "Right Clavicle", name: "Right Clavicle", system: "Musculoskeletal", color_hex: "#ffa500", color_rgb: [255, 165, 0], coverage_pct: 0.20 },
  { id: 2, raw_name: "Left Scapula", name: "Left Scapula", system: "Musculoskeletal", color_hex: "#ff00ff", color_rgb: [255, 0, 255], coverage_pct: 6.53 },
  { id: 3, raw_name: "Right Scapula", name: "Right Scapula", system: "Musculoskeletal", color_hex: "#ff1493", color_rgb: [255, 20, 147], coverage_pct: 7.73 },
  { id: 4, raw_name: "Left Lung", name: "Left Lung Field", system: "Pulmonary", color_hex: "#00bfff", color_rgb: [0, 191, 255], coverage_pct: 21.03 },
  { id: 5, raw_name: "Right Lung", name: "Right Lung Field", system: "Pulmonary", color_hex: "#1e90ff", color_rgb: [30, 144, 255], coverage_pct: 24.39 },
  { id: 6, raw_name: "Left Hilus Pulmonis", name: "Left Pulmonary Hilum", system: "Pulmonary", color_hex: "#8a2be2", color_rgb: [138, 43, 226], coverage_pct: 2.50 },
  { id: 7, raw_name: "Right Hilus Pulmonis", name: "Right Pulmonary Hilum", system: "Pulmonary", color_hex: "#9370db", color_rgb: [147, 112, 219], coverage_pct: 2.10 },
  { id: 8, raw_name: "Heart", name: "Cardiac Silhouette", system: "Cardiovascular", color_hex: "#ff4500", color_rgb: [255, 69, 0], coverage_pct: 9.38 },
  { id: 9, raw_name: "Aorta", name: "Aortic Arch & Knob", system: "Cardiovascular", color_hex: "#ffd700", color_rgb: [255, 215, 0], coverage_pct: 3.48 },
  { id: 10, raw_name: "Facies Diaphragmatica", name: "Diaphragmatic Surface", system: "Diaphragmatic", color_hex: "#32cd32", color_rgb: [50, 205, 50], coverage_pct: 4.88 },
  { id: 11, raw_name: "Mediastinum", name: "Mediastinum", system: "Cardiovascular", color_hex: "#00fa9a", color_rgb: [0, 250, 154], coverage_pct: 3.55 },
  { id: 12, raw_name: "Weasand", name: "Trachea / Main Bronchi", system: "Pulmonary", color_hex: "#dc143c", color_rgb: [220, 20, 60], coverage_pct: 2.54 },
  { id: 13, raw_name: "Spine", name: "Thoracic Spine", system: "Musculoskeletal", color_hex: "#7cfc00", color_rgb: [124, 252, 0], coverage_pct: 12.33 },
];

export const SYSTEM_TABS = [
  { id: "ALL", label: "All Anatomy", icon: "🫁" },
  { id: "Pulmonary", label: "Pulmonary", icon: "💨" },
  { id: "Cardiovascular", label: "Cardiovascular", icon: "❤️" },
  { id: "Musculoskeletal", label: "Skeletal", icon: "🦴" },
  { id: "Diaphragmatic", label: "Diaphragm", icon: "〰️" },
];

export default function CxrSegmentationView({
  evidence = {},
  urls = {},
  show = true,
  annotations = [],
  selectedAnnotation = null,
  onSelectAnnotation = null,
  onEditAnnotation = null,
  onDeleteAnnotation = null,
  onRequestNewNote = null,
  isAddNoteMode = false,
  onToggleAddNoteMode = null,
}) {
  // View mode tab: 'composite' | 'system_Pulmonary' | 'system_Cardiovascular' | 'system_Musculoskeletal' | 'system_Diaphragmatic' | 'gradcam' | 'original'
  const [viewMode, setViewMode] = useState("composite");
  const [splitView, setSplitView] = useState(false);
  const [overlayOpacity, setOverlayOpacity] = useState(0.55);
  const [invert, setInvert] = useState(false);
  const [selectedRegionId, setSelectedRegionId] = useState(null);
  const [hoveredRegionId, setHoveredRegionId] = useState(null);
  const [systemFilter, setSystemFilter] = useState("ALL");
  const [selectedGradcamPathology, setSelectedGradcamPathology] = useState(
    evidence?.gradcam_finding || "Edema"
  );

  // Off-screen canvas for anatomical region click lookup
  const offscreenCanvasRef = useRef(null);
  const [isLayerReady, setIsLayerReady] = useState(false);

  const regions = useMemo(() => {
    return evidence?.cxr_segmentation_regions || DEFAULT_CXR_REGIONS;
  }, [evidence]);

  const filteredRegions = useMemo(() => {
    if (systemFilter === "ALL") return regions;
    return regions.filter((r) => r.system === systemFilter);
  }, [regions, systemFilter]);

  // Base CXR image
  const baseImgSrc = urls.cxr_base_png || urls.gradcam_png || "/fixtures/frames/sample_cxr.png";

  // Pre-load composite segmentation layer into hidden canvas for coordinate probing
  const compositeLayerUrl = urls.cxr_segmentation_layer_png;
  useEffect(() => {
    if (!compositeLayerUrl) return;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.src = compositeLayerUrl;
    img.onload = () => {
      const cvs = document.createElement("canvas");
      cvs.width = img.naturalWidth || 448;
      cvs.height = img.naturalHeight || 496;
      const ctx = cvs.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      offscreenCanvasRef.current = { canvas: cvs, ctx, width: cvs.width, height: cvs.height };
      setIsLayerReady(true);
    };
  }, [compositeLayerUrl]);

  // Lookup anatomical region from click coordinates
  const lookupRegion = (normX, normY) => {
    if (!offscreenCanvasRef.current) return "Chest Radiograph (PA View)";
    const { ctx, width, height } = offscreenCanvasRef.current;
    const px = Math.floor(Math.max(0, Math.min(width - 1, normX * width)));
    const py = Math.floor(Math.max(0, Math.min(height - 1, normY * height)));

    try {
      const pixel = ctx.getImageData(px, py, 1, 1).data;
      const [r, g, b, a] = pixel;
      if (a < 30) {
        return "Chest Radiograph (PA View)";
      }

      // Match closest color from regions
      let bestDist = Infinity;
      let matchedRegion = null;
      for (const reg of regions) {
        const [cr, cg, cb] = reg.color_rgb;
        const dist = Math.hypot(r - cr, g - cg, b - cb);
        if (dist < bestDist) {
          bestDist = dist;
          matchedRegion = reg;
        }
      }
      if (matchedRegion && bestDist < 100) {
        return `${matchedRegion.name} (${matchedRegion.system})`;
      }
    } catch (err) {
      console.warn("Could not sample canvas pixel:", err);
    }
    return "Chest Radiograph (PA View)";
  };

  // Determine current overlay layer image source
  const getActiveOverlaySrc = () => {
    if (viewMode === "original") return null;
    if (viewMode === "gradcam") {
      const gList = evidence?.cxr_gradcam_pathologies || [];
      const match = gList.find(
        (g) =>
          g.name?.toLowerCase() === selectedGradcamPathology?.toLowerCase() ||
          g.slug === selectedGradcamPathology?.toLowerCase()
      );
      if (match && match.layer_url) return match.layer_url;
      return urls.gradcam_layer_png || urls.gradcam_heatmap_png || null;
    }
    
    // If a specific region is isolated
    if (selectedRegionId !== null) {
      const reg = regions.find((r) => r.id === selectedRegionId);
      if (reg && reg.mask_url) return reg.mask_url;
      if (reg && urls[`cxr_mask_${reg.id}_png`]) return urls[`cxr_mask_${reg.id}_png`];
    }

    if (viewMode === "system_Pulmonary") return urls.cxr_segmentation_pulmonary_png || urls.cxr_segmentation_layer_png;
    if (viewMode === "system_Cardiovascular") return urls.cxr_segmentation_cardiovascular_png || urls.cxr_segmentation_layer_png;
    if (viewMode === "system_Musculoskeletal") return urls.cxr_segmentation_musculoskeletal_png || urls.cxr_segmentation_layer_png;
    if (viewMode === "system_Diaphragmatic") return urls.cxr_segmentation_diaphragmatic_png || urls.cxr_segmentation_layer_png;

    return urls.cxr_segmentation_layer_png || null;
  };

  const activeOverlaySrc = getActiveOverlaySrc();

  // Handle click on radiograph for pinpoint annotation
  const handleRadiographClick = (e, panelName = "Main") => {
    if (!isAddNoteMode && e.type !== "contextmenu") return;
    if (e.type === "contextmenu") e.preventDefault();

    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    const normX = Math.max(0, Math.min(1, clickX / rect.width));
    const normY = Math.max(0, Math.min(1, clickY / rect.height));

    const detectedRegion = lookupRegion(normX, normY);

    onRequestNewNote?.({
      modality: "CR",
      coordinate_space: "IMAGE_NORMALIZED",
      coordinate_x: normX,
      coordinate_y: normY,
      slice_index: 0,
      segmentation_region: detectedRegion,
      viewer_context: {
        panel: panelName,
        pixel_coords: {
          x: Math.round(normX * (offscreenCanvasRef.current?.width || 448)),
          y: Math.round(normY * (offscreenCanvasRef.current?.height || 496)),
        },
        view_mode: viewMode,
        isolated_target: selectedRegionId,
      },
      metadata: {
        x_pct: Math.round(normX * 100),
        y_pct: Math.round(normY * 100),
        anatomical_structure: detectedRegion,
      },
    });
  };

  // Toggle single region isolation
  const handleToggleRegion = (regId) => {
    if (selectedRegionId === regId) {
      setSelectedRegionId(null);
    } else {
      setSelectedRegionId(regId);
      if (viewMode === "original" || viewMode === "gradcam") {
        setViewMode("composite");
      }
    }
  };

  return (
    <div className={`cxr-segmentation-workstation ${isAddNoteMode ? "pinpoint-active-mode" : ""}`} data-testid="cxr-segmentation-view">
      {/* Workstation Top Toolbar */}
      <div className="cxr-workstation-toolbar" role="toolbar" aria-label="CXR Segmentation Toolbar">
        {onToggleAddNoteMode && (
          <button
            type="button"
            className={`btn-pin-mode ${isAddNoteMode ? "active" : ""}`}
            onClick={onToggleAddNoteMode}
            title="Drop a pinpoint clinical note onto the radiograph"
            data-testid="cxr-add-note-btn"
          >
            📍 {isAddNoteMode ? "Pin Active" : "Add Note"}
          </button>
        )}

        {/* View Mode Buttons */}
        <div className="cxr-mode-group" role="group" aria-label="Anatomical Mode Switcher">
          <button
            type="button"
            className={`mode-tab-btn ${viewMode === "composite" && selectedRegionId === null ? "active" : ""}`}
            onClick={() => { setViewMode("composite"); setSelectedRegionId(null); }}
            title="Render all 14 segmented anatomical structures color-coded simultaneously"
          >
            🎨 All Segments
          </button>
          <button
            type="button"
            className={`mode-tab-btn ${viewMode === "system_Pulmonary" && selectedRegionId === null ? "active" : ""}`}
            onClick={() => { setViewMode("system_Pulmonary"); setSelectedRegionId(null); }}
            title="Filter to Pulmonary system (Lungs, Hila, Airways)"
          >
            🫁 Pulmonary
          </button>
          <button
            type="button"
            className={`mode-tab-btn ${viewMode === "system_Cardiovascular" && selectedRegionId === null ? "active" : ""}`}
            onClick={() => { setViewMode("system_Cardiovascular"); setSelectedRegionId(null); }}
            title="Filter to Cardiovascular system (Heart, Aorta, Mediastinum)"
          >
            ❤️ Cardio
          </button>
          <button
            type="button"
            className={`mode-tab-btn ${viewMode === "system_Musculoskeletal" && selectedRegionId === null ? "active" : ""}`}
            onClick={() => { setViewMode("system_Musculoskeletal"); setSelectedRegionId(null); }}
            title="Filter to Musculoskeletal system (Clavicles, Scapulae, Spine)"
          >
            🦴 Skeletal
          </button>
          <button
            type="button"
            className={`mode-tab-btn ${viewMode === "system_Diaphragmatic" && selectedRegionId === null ? "active" : ""}`}
            onClick={() => { setViewMode("system_Diaphragmatic"); setSelectedRegionId(null); }}
            title="Filter to Diaphragmatic surface"
          >
            〰️ Diaphragm
          </button>
          <button
            type="button"
            className={`mode-tab-btn ${viewMode === "gradcam" ? "active" : ""}`}
            onClick={() => { setViewMode("gradcam"); setSelectedRegionId(null); }}
            title="View DenseNet explainability Grad-CAM saliency heatmap"
          >
            🔥 Grad-CAM
          </button>
          <button
            type="button"
            className={`mode-tab-btn ${viewMode === "original" ? "active" : ""}`}
            onClick={() => { setViewMode("original"); setSelectedRegionId(null); }}
            title="View pure un-annotated chest radiograph"
          >
            📷 Original
          </button>
        </div>

        {/* Real-time Opacity Slider */}
        {viewMode !== "original" && (
          <div className="cxr-opacity-control" title="Adjust segmentation overlay opacity">
            <span className="opacity-label">Opacity</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={overlayOpacity}
              onChange={(e) => setOverlayOpacity(parseFloat(e.target.value))}
              className="opacity-slider"
              aria-label="Overlay Opacity"
              data-testid="cxr-opacity-slider"
            />
            <span className="opacity-val mono">{Math.round(overlayOpacity * 100)}%</span>
          </div>
        )}

        {/* View Layout Controls */}
        <div className="cxr-extra-tools">
          <button
            type="button"
            className={`btn-tool ${splitView ? "active" : ""}`}
            onClick={() => setSplitView(!splitView)}
            title="Toggle side-by-side comparison with original radiograph"
            data-testid="cxr-split-view-btn"
          >
            ◫ Split View
          </button>
          <button
            type="button"
            className={`btn-tool ${invert ? "active" : ""}`}
            onClick={() => setInvert(!invert)}
            title="Invert radiograph grayscale levels (bone vs soft tissue)"
          >
            🌓 Invert
          </button>
          <button
            type="button"
            className="btn-tool"
            onClick={() => {
              setViewMode("composite");
              setSelectedRegionId(null);
              setOverlayOpacity(0.55);
              setInvert(false);
              setSplitView(false);
            }}
            title="Reset viewer settings"
          >
            ↺ Reset
          </button>
        </div>
      </div>

      {/* Pinpoint Mode Instruction HUD */}
      {isAddNoteMode && (
        <div className="cxr-pin-instruction-hud">
          <span className="pulse-dot"></span>
          <span>
            <strong>Pinpoint Active:</strong> Click any anatomical structure on the radiograph to attach a clinical note. Anatomy is auto-detected.
          </span>
        </div>
      )}

      {/* Main Radiograph Viewing Stage */}
      <div className={`cxr-viewing-stage ${splitView ? "split-mode" : "single-mode"}`}>
        {/* Left Panel in Split View: Clean Original Radiograph */}
        {splitView && (
          <div className="cxr-panel-wrapper original-panel">
            <div className="cxr-panel-header">
              <span className="panel-badge">Reference Baseline</span>
              <span className="panel-title">Original Chest Radiograph (PA)</span>
            </div>
            <div
              className="cxr-viewport-frame"
              onClick={(e) => handleRadiographClick(e, "Original Split")}
              onContextMenu={(e) => handleRadiographClick(e, "Original Split")}
            >
              <img
                src={baseImgSrc}
                alt="Original Chest Radiograph"
                className={`cxr-stage-img ${invert ? "inverted" : ""}`}
              />
            </div>
          </div>
        )}

        {/* Primary Interactive Workstation Panel */}
        <div className="cxr-panel-wrapper active-panel">
          <div className="cxr-panel-header">
            <div className="header-left">
              <span className="panel-badge highlight">
                {selectedRegionId !== null
                  ? `Isolated: ${regions.find((r) => r.id === selectedRegionId)?.name}`
                  : viewMode === "composite"
                  ? "PSPNet Multi-Anatomical Segmentation (14 Structures)"
                  : viewMode === "gradcam"
                  ? `DenseNet Grad-CAM: ${evidence?.gradcam_finding || "Driving Pathology"}`
                  : viewMode === "original"
                  ? "Native Grayscale Radiograph"
                  : `${viewMode.replace("system_", "")} Organ System Overlay`}
              </span>
            </div>
            {selectedRegionId !== null && (
              <button
                type="button"
                className="btn-clear-isolation"
                onClick={() => setSelectedRegionId(null)}
                title="Show all anatomical segments"
              >
                ✕ Clear Isolation
              </button>
            )}
          </div>

          <div
            className="cxr-viewport-frame"
            onClick={(e) => handleRadiographClick(e, "Main Overlaid")}
            onContextMenu={(e) => handleRadiographClick(e, "Main Overlaid")}
          >
            {/* Base Image */}
            <img
              src={baseImgSrc}
              alt="Chest Radiograph Base"
              className={`cxr-stage-img ${invert ? "inverted" : ""}`}
            />

            {/* Overlaid Segmentation / Grad-CAM Layer */}
            {activeOverlaySrc && (
              <img
                src={activeOverlaySrc}
                alt="Anatomical Segmentation Overlay"
                className="cxr-overlay-layer"
                style={{ opacity: overlayOpacity }}
                data-testid="cxr-overlay-img"
              />
            )}

            {/* Clinician Pinpoint Annotations on CXR */}
            {annotations.map((ann) => {
              if (ann.coordinate_x == null || ann.coordinate_y == null) return null;
              const isSel = ann.id === selectedAnnotation?.id || ann.annotation_id === selectedAnnotation?.annotation_id;
              const xPct = ann.coordinate_x * 100;
              const yPct = ann.coordinate_y * 100;
              const posClass = yPct < 25 ? "popover-below" : xPct > 75 ? "popover-left" : xPct < 25 ? "popover-right" : "popover-above";

              return (
                <div
                  key={ann.id || ann.annotation_id}
                  className={`pin-marker-point ${isSel ? "selected" : ""}`}
                  style={{ left: `${xPct}%`, top: `${yPct}%` }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectAnnotation?.(ann);
                  }}
                  title={`${ann.note_text} (${ann.created_by || "radiologist"})`}
                >
                  <span className="pin-dot"></span>
                  <span className="pin-pulse"></span>
                  {isSel && (
                    <div className={`pin-tooltip-popover ${posClass}`} onClick={(e) => e.stopPropagation()}>
                      <div className="popover-meta-header">
                        <span className="popover-author">{ann.created_by?.split("@")[0] || "Radiologist"}</span>
                        {ann.segmentation_region && (
                          <span className="popover-region-tag">{ann.segmentation_region}</span>
                        )}
                      </div>
                      <div className="popover-body-text">{ann.note_text}</div>
                      <div className="popover-action-row">
                        {onEditAnnotation && (
                          <button
                            type="button"
                            className="btn-popover-action edit"
                            onClick={() => onEditAnnotation(ann)}
                            title="Edit this finding"
                          >
                            ✎ Edit
                          </button>
                        )}
                        {onDeleteAnnotation && (
                          <button
                            type="button"
                            className="btn-popover-action delete"
                            onClick={() => onDeleteAnnotation(ann.id || ann.annotation_id)}
                            title="Delete this finding"
                          >
                            🗑 Delete
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Bottom Panel: Switch between Grad-CAM Saliency Studio and PSPNet Anatomy Chips */}
      {viewMode === "gradcam" ? (
        <div className="cxr-gradcam-panel" data-testid="cxr-gradcam-panel">
          <div className="gradcam-panel-header">
            <div className="header-title">
              <span className="anatomy-icon">🔥</span>
              <h4>DenseNet-121 Grad-CAM Saliency Explainability:</h4>
              <span className="hint-text">Select any target pathology to view model convolutional attention heatmap</span>
            </div>
            <div className="gradcam-active-badge">
              Active Finding: <strong className="highlight-text">{selectedGradcamPathology}</strong>
            </div>
          </div>

          {/* Pathology Chips Grid */}
          <div className="gradcam-pathologies-grid">
            {(evidence?.cxr_gradcam_pathologies || [
              { name: "Edema", confidence: 53.4, signal: 1.0, coverage: 0.053 },
              { name: "Consolidation", confidence: 48.2, signal: 0.629, coverage: 0.029 },
              { name: "Effusion", confidence: 39.9, signal: 0.571, coverage: 0.073 },
              { name: "Cardiomegaly", confidence: 50.6, signal: 0.506, coverage: 0.060 },
              { name: "Pneumonia", confidence: 45.0, signal: 0.450, coverage: 0.066 },
              { name: "Atelectasis", confidence: 38.1, signal: 0.381, coverage: 0.035 },
              { name: "Nodule", confidence: 69.7, signal: 0.697, coverage: 0.034 },
              { name: "Infiltration", confidence: 51.5, signal: 0.515, coverage: 0.056 },
              { name: "Mass", confidence: 72.1, signal: 0.721, coverage: 0.012 },
              { name: "Pneumothorax", confidence: 38.4, signal: 0.384, coverage: 0.046 },
              { name: "Lung Opacity", confidence: 77.3, signal: 0.773, coverage: 0.029 },
              { name: "Fibrosis", confidence: 51.5, signal: 0.515, coverage: 0.015 },
              { name: "Enlarged Cardiomediastinum", confidence: 50.7, signal: 0.507, coverage: 0.044 },
            ]).map((p) => {
              const isSel = p.name.toLowerCase() === selectedGradcamPathology.toLowerCase() || p.slug === selectedGradcamPathology.toLowerCase();
              return (
                <button
                  key={p.name || p.slug}
                  type="button"
                  className={`gradcam-pathology-chip ${isSel ? "active" : ""}`}
                  onClick={() => setSelectedGradcamPathology(p.name)}
                  title={`Click to view Grad-CAM attention heatmap for ${p.name} (${p.confidence}%)`}
                >
                  <span className="pathology-fire-icon">🔥</span>
                  <span className="pathology-name">{p.name}</span>
                  <span className={`pathology-conf-badge ${p.confidence > 50 ? "high" : ""}`}>
                    {p.confidence}%
                  </span>
                </button>
              );
            })}
          </div>

          <p className="gradcam-rationale-note">
            <span className="bold">DenseNet-121 Attention Mapping:</span> High thermal intensity (red, orange, yellow in JET colormap) isolates the convolutional feature map regions that motivated the neural network's decision for <span className="highlight-text">{selectedGradcamPathology}</span>.
          </p>
        </div>
      ) : (
        /* 14 Anatomical Targets Panel */
        <div className="cxr-anatomy-panel">
          <div className="anatomy-panel-header">
            <div className="header-title">
              <span className="anatomy-icon">🧬</span>
              <h4>PSPNet 14-Target Anatomical Segmentation:</h4>
              <span className="hint-text">Click any region to isolate. Hover to highlight.</span>
            </div>

            {/* Organ System Filter Buttons */}
            <div className="system-filter-tabs" role="tablist">
              {SYSTEM_TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={`system-tab-chip ${systemFilter === tab.id ? "active" : ""}`}
                  onClick={() => setSystemFilter(tab.id)}
                >
                  <span>{tab.icon}</span> {tab.label}
                </button>
              ))}
            </div>
          </div>

          {/* 14 Anatomical Chips Grid */}
          <div className="regions-chips-grid">
            {filteredRegions.map((region) => {
              const isIsolated = selectedRegionId === region.id;
              return (
                <button
                  key={region.id}
                  type="button"
                  className={`anatomy-chip ${isIsolated ? "isolated" : ""}`}
                  onClick={() => handleToggleRegion(region.id)}
                  onMouseEnter={() => setHoveredRegionId(region.id)}
                  onMouseLeave={() => setHoveredRegionId(null)}
                  title={`Click to isolate ${region.name} (${region.system}). Coverage: ${region.coverage_pct}%`}
                  style={{
                    borderColor: isIsolated ? region.color_hex : undefined,
                    boxShadow: isIsolated ? `0 0 10px ${region.color_hex}66` : undefined,
                  }}
                >
                  <span
                    className="chip-color-dot"
                    style={{
                      backgroundColor: region.color_hex,
                      boxShadow: `0 0 6px ${region.color_hex}`,
                    }}
                  ></span>
                  <span className="chip-name">{region.name}</span>
                  <span className="chip-system-badge">{region.system}</span>
                  <span className="chip-coverage-val mono">{region.coverage_pct}%</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
