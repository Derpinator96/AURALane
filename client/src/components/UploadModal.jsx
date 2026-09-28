import { useState } from "react";
import { api } from "../api.js";
import { UploadIcon } from "./Icons.jsx";

/**
 * UploadModal: Clinical Ingestion Interface with Strict Pipeline Separation:
 * A) Brain Tumor MRI: Multi-sequence workflow (T1, T1c, T2, FLAIR) -> MONAI SegResNet
 * B) Alzheimer's MRI: Single-sequence T1 workflow -> 3D DenseNet121 Cognitive Classifier
 * C) Chest Radiography: DICOM / Image -> TorchXRayVision DenseNet
 * D) Head CT: DICOM -> Intracranial Hemorrhage & Midline Shift
 */
export default function UploadModal({ token, onClose, onStudyIngested }) {
  const [activeTab, setActiveTab] = useState("mri_tumor"); // 'mri_tumor' | 'mri_alzheimer' | 'cr' | 'ct'
  const [patientId, setPatientId] = useState("");
  const [status, setStatus] = useState("idle"); // idle | processing | success | error
  const [currentStep, setCurrentStep] = useState(0);
  const [result, setResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");

  // Brain Tumor multi-sequence files
  const [tumorT1c, setTumorT1c] = useState(null);
  const [tumorT1, setTumorT1] = useState(null);
  const [tumorT2, setTumorT2] = useState(null);
  const [tumorFlair, setTumorFlair] = useState(null);

  // Alzheimer's single T1 file
  const [alzheimerT1, setAlzheimerT1] = useState(null);

  // Single file for CR or CT
  const [singleFile, setSingleFile] = useState(null);

  const PIPELINE_STEPS = [
    "Receiving and staging imaging payload",
    "Running DICOM PS3.15 de-identification and OCR text masking",
    "Constructing input tensors and executing AI model inference",
    "Calibrating acuity scores and evaluating triage priority lanes",
    "Registering study into live active worklist",
  ];

  const handleQuickLoadTumor = async () => {
    setStatus("processing");
    setCurrentStep(0);
    const stepInterval = setInterval(() => {
      setCurrentStep((prev) => (prev < PIPELINE_STEPS.length - 1 ? prev + 1 : prev));
    }, 400);

    try {
      const res = await api.mriDemo(token);
      clearInterval(stepInterval);
      setCurrentStep(PIPELINE_STEPS.length - 1);
      setResult(res.study);
      setStatus("success");
      if (onStudyIngested) onStudyIngested(res.study);
    } catch (err) {
      clearInterval(stepInterval);
      setStatus("error");
      setErrorMessage(err.message || "Failed to quick load BraTS demo study.");
    }
  };

  const handleQuickLoadAlzheimer = async () => {
    setStatus("processing");
    setCurrentStep(0);
    const stepInterval = setInterval(() => {
      setCurrentStep((prev) => (prev < PIPELINE_STEPS.length - 1 ? prev + 1 : prev));
    }, 400);

    try {
      const res = await api.alzheimerDemo(token);
      clearInterval(stepInterval);
      setCurrentStep(PIPELINE_STEPS.length - 1);
      setResult(res.study);
      setStatus("success");
      if (onStudyIngested) onStudyIngested(res.study);
    } catch (err) {
      clearInterval(stepInterval);
      setStatus("error");
      setErrorMessage(err.message || "Failed to quick load Alzheimer test study.");
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setStatus("processing");
    setCurrentStep(0);
    setErrorMessage("");

    const stepInterval = setInterval(() => {
      setCurrentStep((prev) => (prev < PIPELINE_STEPS.length - 1 ? prev + 1 : prev));
    }, 500);

    try {
      const formData = new FormData();

      if (activeTab === "mri_tumor") {
        const primaryFile = tumorT1c || tumorT1 || tumorT2 || tumorFlair;
        if (!primaryFile) throw new Error("Please select at least one Brain Tumor MRI sequence file.");
        formData.append("file", primaryFile);
        formData.append("modality", "MR");
        formData.append("workflow", "TUMOR");
      } else if (activeTab === "mri_alzheimer") {
        if (!alzheimerT1) throw new Error("Please select a T1-weighted NIfTI volume for Alzheimer's analysis.");
        formData.append("file", alzheimerT1);
        formData.append("modality", "MR");
        formData.append("workflow", "ALZHEIMER");
      } else if (activeTab === "cr") {
        if (!singleFile) throw new Error("Please select a Chest X-ray DICOM or image file.");
        formData.append("file", singleFile);
        formData.append("modality", "CR");
      } else if (activeTab === "ct") {
        if (!singleFile) throw new Error("Please select a Head CT DICOM file.");
        formData.append("file", singleFile);
        formData.append("modality", "CT");
        formData.append("workflow", "CT");
      }

      if (patientId.trim()) {
        formData.append("patient_id", patientId.trim());
      }

      const response = await api.upload(token, formData);
      clearInterval(stepInterval);
      setCurrentStep(PIPELINE_STEPS.length - 1);
      setResult(response.study);
      setStatus("success");

      if (onStudyIngested) onStudyIngested(response.study);
    } catch (err) {
      clearInterval(stepInterval);
      setStatus("error");
      setErrorMessage(err.message || "Failed to ingest study through pipeline.");
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose} data-testid="upload-modal-backdrop">
      <div className="modal-card wide-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 className="modal-title">Clinical Study Ingestion Portal</h2>
            <p className="modal-subtitle">
              Upload diagnostic scans for real-time AWS pipeline ingestion, neural inference, and priority triage
            </p>
          </div>
          <button type="button" className="btn-close" onClick={onClose} aria-label="Close modal">
            ✕
          </button>
        </div>

        {/* Workflow Tabs */}
        <div className="workflow-tabs" role="tablist">
          <button
            type="button"
            className={`workflow-tab ${activeTab === "mri_tumor" ? "active" : ""}`}
            onClick={() => setActiveTab("mri_tumor")}
            data-testid="tab-tumor-mri"
          >
            Brain Tumor MRI (Multi-Seq)
          </button>
          <button
            type="button"
            className={`workflow-tab ${activeTab === "mri_alzheimer" ? "active" : ""}`}
            onClick={() => setActiveTab("mri_alzheimer")}
            data-testid="tab-alzheimer-mri"
          >
            Alzheimer's MRI (T1-Only)
          </button>
          <button
            type="button"
            className={`workflow-tab ${activeTab === "cr" ? "active" : ""}`}
            onClick={() => setActiveTab("cr")}
            data-testid="tab-cr"
          >
            Chest Radiography
          </button>
          <button
            type="button"
            className={`workflow-tab ${activeTab === "ct" ? "active" : ""}`}
            onClick={() => setActiveTab("ct")}
            data-testid="tab-ct"
          >
            Head CT
          </button>
        </div>

        {status === "idle" && (
          <form onSubmit={handleSubmit} className="upload-form">
            {/* WORKFLOW 1: BRAIN TUMOR MRI (MULTI-SEQUENCE) */}
            {activeTab === "mri_tumor" && (
              <div className="tab-pane">
                <div className="pipeline-notice notice-purple">
                  <span className="notice-icon">ℹ️</span>
                  <div>
                    <span className="bold">Multi-Sequence Tumor Requirement:</span> SegResNet volumetric segmentation operates on co-registered 4-channel tensors: T1ce (contrast), T1 (native), T2, and FLAIR.
                  </div>
                </div>

                <div className="multi-sequence-grid">
                  <div className="seq-dropzone">
                    <span className="seq-label">1. T1 Contrast (T1ce / T1c) *</span>
                    <input
                      type="file"
                      id="file-t1c"
                      className="hidden-file-input"
                      accept=".nii,.nii.gz,.dcm"
                      onChange={(e) => setTumorT1c(e.target.files[0] || null)}
                    />
                    <label htmlFor="file-t1c" className="seq-drop-box">
                      {tumorT1c ? <span className="mono seq-name">{tumorT1c.name}</span> : <span>+ Select T1c Volume</span>}
                    </label>
                  </div>

                  <div className="seq-dropzone">
                    <span className="seq-label">2. T1 Native (ch1)</span>
                    <input
                      type="file"
                      id="file-t1"
                      className="hidden-file-input"
                      accept=".nii,.nii.gz,.dcm"
                      onChange={(e) => setTumorT1(e.target.files[0] || null)}
                    />
                    <label htmlFor="file-t1" className="seq-drop-box">
                      {tumorT1 ? <span className="mono seq-name">{tumorT1.name}</span> : <span>+ Select T1 Native</span>}
                    </label>
                  </div>

                  <div className="seq-dropzone">
                    <span className="seq-label">3. T2 Weighted (ch2)</span>
                    <input
                      type="file"
                      id="file-t2"
                      className="hidden-file-input"
                      accept=".nii,.nii.gz,.dcm"
                      onChange={(e) => setTumorT2(e.target.files[0] || null)}
                    />
                    <label htmlFor="file-t2" className="seq-drop-box">
                      {tumorT2 ? <span className="mono seq-name">{tumorT2.name}</span> : <span>+ Select T2 Volume</span>}
                    </label>
                  </div>

                  <div className="seq-dropzone">
                    <span className="seq-label">4. FLAIR (ch3)</span>
                    <input
                      type="file"
                      id="file-flair"
                      className="hidden-file-input"
                      accept=".nii,.nii.gz,.dcm"
                      onChange={(e) => setTumorFlair(e.target.files[0] || null)}
                    />
                    <label htmlFor="file-flair" className="seq-drop-box">
                      {tumorFlair ? <span className="mono seq-name">{tumorFlair.name}</span> : <span>+ Select FLAIR</span>}
                    </label>
                  </div>
                </div>

                <div className="quick-action-bar">
                  <span className="quick-hint">Don't have 4 local NIfTI sequences on hand?</span>
                  <button
                    type="button"
                    className="btn-quick-demo"
                    onClick={handleQuickLoadTumor}
                    data-testid="btn-quick-load-brats"
                  >
                    Quick Load Verified BraTS Demo Case 00000057
                  </button>
                </div>
              </div>
            )}

            {/* WORKFLOW 2: ALZHEIMER'S MRI (T1-ONLY) */}
            {activeTab === "mri_alzheimer" && (
              <div className="tab-pane">
                <div className="pipeline-notice notice-blue">
                  <span className="notice-badge">MR-AD</span>
                  <div>
                    <span className="bold">Dedicated T1-Only Cognitive Pipeline:</span> 3D DenseNet121 evaluates atrophy patterns on a single T1-weighted structural volume. Does not require or generate tumor segmentations.
                  </div>
                </div>

                <div className="single-dropzone-wrapper">
                  <input
                    type="file"
                    id="file-alz-t1"
                    className="hidden-file-input"
                    accept=".nii,.nii.gz,.dcm"
                    onChange={(e) => setAlzheimerT1(e.target.files[0] || null)}
                  />
                  <label htmlFor="file-alz-t1" className="single-drop-box">
                    <div className="drop-icon"><UploadIcon size={28} /></div>
                    {alzheimerT1 ? (
                      <div className="file-info">
                        <span className="mono bold">{alzheimerT1.name}</span>
                        <span>{(alzheimerT1.size / (1024 * 1024)).toFixed(2)} MB</span>
                        <span className="change-hint">Click to replace file</span>
                      </div>
                    ) : (
                      <div>
                        <span className="prompt-text">Click or drop T1 Structural MRI volume (.nii, .nii.gz)</span>
                        <span className="sub-hint">e.g. OASIS-1, OASIS-2, or radiata-ai test split scan</span>
                      </div>
                    )}
                  </label>
                </div>

                <div className="quick-action-bar">
                  <span className="quick-hint">Test set evaluation:</span>
                  <button
                    type="button"
                    className="btn-quick-demo"
                    onClick={handleQuickLoadAlzheimer}
                    data-testid="btn-quick-load-alzheimer"
                  >
                    Quick Load OASIS Alzheimer's Case (AD_01)
                  </button>
                </div>
              </div>
            )}

            {/* WORKFLOW 3: CHEST RADIOGRAPHY */}
            {activeTab === "cr" && (
              <div className="tab-pane">
                <div className="pipeline-notice notice-indigo">
                  <span className="notice-badge">CXR</span>
                  <div>
                    <span className="bold">Chest X-Ray Pipeline:</span> TorchXRayVision DenseNet-121 screens for 18 thoracic pathologies with calibrated clinical urgencies and Grad-CAM explainability.
                  </div>
                </div>

                <div className="single-dropzone-wrapper">
                  <input
                    type="file"
                    id="file-cr"
                    className="hidden-file-input"
                    accept=".dcm,.dicom,.png,.jpg,.jpeg,.zip"
                    onChange={(e) => setSingleFile(e.target.files[0] || null)}
                  />
                  <label htmlFor="file-cr" className="single-drop-box">
                    <div className="drop-icon"><UploadIcon size={28} /></div>
                    {singleFile ? (
                      <div className="file-info">
                        <span className="mono bold">{singleFile.name}</span>
                        <span>{(singleFile.size / (1024 * 1024)).toFixed(2)} MB</span>
                      </div>
                    ) : (
                      <div>
                        <span className="prompt-text">Drop Chest PA Radiograph (.dcm, .zip, .png)</span>
                        <span className="sub-hint">NIH ChestX-ray14 or hospital DICOM</span>
                      </div>
                    )}
                  </label>
                </div>
              </div>
            )}

            {/* WORKFLOW 4: HEAD CT */}
            {activeTab === "ct" && (
              <div className="tab-pane">
                <div className="pipeline-notice notice-crimson">
                  <span className="notice-badge">CT</span>
                  <div>
                    <span className="bold">Emergency Head CT Triage:</span> High-priority automated screening for acute intracranial hemorrhage, mass effect, and midline shift.
                  </div>
                </div>

                <div className="single-dropzone-wrapper">
                  <input
                    type="file"
                    id="file-ct"
                    className="hidden-file-input"
                    accept=".dcm,.dicom,.zip"
                    onChange={(e) => setSingleFile(e.target.files[0] || null)}
                  />
                  <label htmlFor="file-ct" className="single-drop-box">
                    <div className="drop-icon"><UploadIcon size={28} /></div>
                    {singleFile ? (
                      <div className="file-info">
                        <span className="mono bold">{singleFile.name}</span>
                        <span>{(singleFile.size / (1024 * 1024)).toFixed(2)} MB</span>
                      </div>
                    ) : (
                      <div>
                        <span className="prompt-text">Drop Non-Contrast Head CT Series (.dcm, .zip)</span>
                        <span className="sub-hint">Emergency trauma or stroke protocol</span>
                      </div>
                    )}
                  </label>
                </div>
              </div>
            )}

            <div className="patient-id-row">
              <label className="field-group">
                <span className="field-label">Patient Pseudonym / MRN (Optional):</span>
                <input
                  type="text"
                  placeholder="e.g. PAT-CUSTOM-001"
                  value={patientId}
                  onChange={(e) => setPatientId(e.target.value)}
                  className="field-input mono"
                />
              </label>
            </div>

            <div className="modal-actions">
              <button type="button" className="btn-secondary" onClick={onClose}>
                Cancel
              </button>
              <button
                type="submit"
                className="btn-primary"
                disabled={
                  activeTab === "mri_tumor"
                    ? !tumorT1c && !tumorT1 && !tumorT2 && !tumorFlair
                    : activeTab === "mri_alzheimer"
                    ? !alzheimerT1
                    : !singleFile
                }
              >
                Execute Pipeline & Triage Study
              </button>
            </div>
          </form>
        )}

        {status === "processing" && (
          <div className="stepper-container" data-testid="upload-stepper">
            <h3 className="stepper-title">Executing Clinical Pipeline</h3>
            <p className="stepper-subtitle">Auditing and processing scan across 9 pipeline stages...</p>
            <div className="stepper-list">
              {PIPELINE_STEPS.map((stepText, idx) => {
                const isDone = idx < currentStep;
                const isCurrent = idx === currentStep;
                return (
                  <div key={idx} className={`step-item ${isDone ? "done" : ""} ${isCurrent ? "current" : ""}`}>
                    <div className="step-indicator">
                      {isDone ? "✓" : isCurrent ? <span className="mini-spin">●</span> : idx + 1}
                    </div>
                    <div className="step-text">{stepText}</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {status === "success" && result && (
          <div className="success-container" data-testid="upload-success">
            <div className="success-badge">✓ Pipeline Execution Complete</div>
            <h3 className="success-title">Study Triaged Successfully</h3>
            <p className="success-subtitle">
              The study has been processed, scored, and placed into the active reading queue.
            </p>

            <div className="result-card">
              <div className="result-row">
                <span className="result-label">Assigned Lane:</span>
                <span className={`lanetag lane-${result.lane}`}>{result.lane_label || result.lane}</span>
              </div>
              <div className="result-row">
                <span className="result-label">Patient Identifier:</span>
                <span className="mono">{result.patient_id}</span>
              </div>
              <div className="result-row">
                <span className="result-label">Modality:</span>
                <span>{result.modality} ({result.pool} Reading Pool)</span>
              </div>
              <div className="result-row">
                <span className="result-label">Clinical Acuity:</span>
                <span className="mono bold">{result.acuity ? result.acuity.toFixed(1) : "--"}</span>
              </div>
              <div className="result-row">
                <span className="result-label">Driving Finding:</span>
                <span>{result.driver_label || result.driver || "Unremarkable"}</span>
              </div>
            </div>

            <div className="modal-actions">
              <button type="button" className="btn-primary" onClick={onClose}>
                View in Worklist & Inspect Scans
              </button>
            </div>
          </div>
        )}

        {status === "error" && (
          <div className="error-container">
            <div className="error-icon">✕</div>
            <h3 className="error-title">Ingestion Error</h3>
            <p className="error-message">{errorMessage}</p>
            <div className="modal-actions">
              <button type="button" className="btn-secondary" onClick={() => setStatus("idle")}>
                Try Again
              </button>
              <button type="button" className="btn-primary" onClick={onClose}>
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
