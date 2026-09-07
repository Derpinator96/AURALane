"""AURALane demo server.

    python server.py            then open http://localhost:8000

Two paths, and the page can switch between them live:

  CACHED  reads scores.json, produced offline by prepare.py. Nothing can fail
          during the presentation. This is the default.
  LIVE    runs TorchXRayVision in-process on request, so you can drop an image
          the jury has never seen onto the page and watch it get a lane.

The model is loaded lazily on first use. Hit "Warm up" before you present —
first inference after load takes several seconds and that is a bad silence.
"""
import io
import json
import os
import time

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel
from typing import Optional

import queue_builder
import triage
import modality_router
import explainability

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="AURALane demo")

_model = None
_pathologies = None
_overrides = {}         # study_id -> override payload
_uploaded_bytes = {}    # filename -> bytes
_explain_cache = {}     # (filename, pathology) -> result dict


class OverrideRequest(BaseModel):
    study_id: str
    action: str  # "AGREE" | "DISAGREE" | "OVERRIDE"
    ai_lane: str
    human_lane: Optional[str] = None
    reason: Optional[str] = ""
    reviewer: Optional[str] = "Dr. User"


class ExplainRequest(BaseModel):
    study_id: str
    filename: Optional[str] = ""
    target_pathology: Optional[str] = None
    modality: Optional[str] = "CXR"


def get_model():
    global _model, _pathologies
    if _model is None:
        import torchxrayvision as xrv
        _model = xrv.models.DenseNet(weights="densenet121-res224-all")
        _model.eval()
        _pathologies = _model.pathologies
    return _model


@app.get("/api/queue")
def api_queue():
    """The demo worklist: real model scores, simulated arrival order."""
    try:
        q = queue_builder.build(os.path.join(HERE, "scores.json"))
        # Merge active human overrides
        for s in q.get("studies", []):
            sid = s.get("id")
            if sid in _overrides:
                s["override"] = _overrides[sid]
        return q
    except FileNotFoundError:
        return JSONResponse(
            {"error": "scores.json not found — run `python prepare.py` first."},
            status_code=503)


@app.post("/api/override")
def api_override(req: OverrideRequest):
    """Store human override decision in server memory."""
    rec = {
        "study_id": req.study_id,
        "action": req.action,
        "ai_lane": req.ai_lane,
        "human_lane": req.human_lane or req.ai_lane,
        "reason": req.reason,
        "reviewer": req.reviewer,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    _overrides[req.study_id] = rec
    return {"ok": True, "override": rec}


@app.get("/api/overrides")
def api_get_overrides():
    """Return all stored human overrides."""
    return {"overrides": _overrides}


@app.post("/api/explain")
def api_explain(req: ExplainRequest):
    """Generate or retrieve cached Grad-CAM heatmap for a study finding."""
    mod = (req.modality or "CXR").upper()
    if mod != "CXR":
        return {
            "supported": False,
            "reason": f"Explainability unavailable for {mod} status [PROTOTYPE/EXPERIMENTAL].",
            "legend": "Explainability unavailable for this prototype study."
        }

    pathology = req.target_pathology or "Pneumothorax"
    cache_key = (req.study_id, req.filename, pathology)
    if cache_key in _explain_cache:
        return _explain_cache[cache_key]

    # Resolve image source
    source = None
    if req.filename and req.filename in _uploaded_bytes:
        source = io.BytesIO(_uploaded_bytes[req.filename])
    elif req.filename:
        disk_path = os.path.join(HERE, "images", req.filename)
        if os.path.exists(disk_path):
            source = disk_path

    if not source:
        return {
            "supported": False,
            "reason": f"Source image asset '{req.filename}' not found on disk for this pre-scored study.",
            "legend": "Explainability unavailable — original image asset not installed locally."
        }

    try:
        model = get_model()
        res = explainability.generate_explainability(model, source, pathology)
        if res.get("supported"):
            _explain_cache[cache_key] = res
        return res
    except Exception as e:
        return {
            "supported": False,
            "reason": f"Explainability error: {e}",
            "legend": "Explainability generation failed."
        }


@app.post("/api/warm")
def api_warm():
    t = time.time()
    get_model()
    return {"ok": True, "seconds": round(time.time() - t, 2)}


@app.get("/api/health")
def api_health():
    return {"model_loaded": _model is not None,
            "scores": os.path.exists(os.path.join(HERE, "scores.json")),
            "overrides_count": len(_overrides)}


@app.post("/api/score")
async def api_score(file: UploadFile = File(...), modality: str = "CXR"):
    """Live inference on an image the jury supplies."""
    modality_upper = modality.upper()

    raw = await file.read()
    if file.filename:
        _uploaded_bytes[file.filename] = raw

    if modality_upper != "CXR":
        # CT / MRI prototype routing
        inf_res = modality_router.route(modality_upper, preset="critical" if "crit" in file.filename.lower() else None)
        res = triage.score(inf_res.preds_dict, modality=modality_upper)
        res.update({
            "filename": file.filename,
            "modality": modality_upper,
            "body_part": inf_res.body_part,
            "model_status": inf_res.status,
            "model_name": inf_res.model_name,
            "data_source": "DEMO FIXTURE",
            "model_explanation": "Demo fixture — not live model inference.",
            "inference_ms": 12,
        })
        return res

    # CXR LIVE MODEL INFERENCE
    import imaging

    t0 = time.time()
    model = get_model()
    load_ms = round((time.time() - t0) * 1000)

    t1 = time.time()
    try:
        preds = imaging.predict(model, io.BytesIO(raw))
    except Exception as e:
        return JSONResponse(
            {"error": f"could not read {file.filename!r} as an image: {e}"},
            status_code=400)
    infer_ms = round((time.time() - t1) * 1000)

    result = triage.score(preds, modality="CXR")
    result.update({
        "filename": file.filename,
        "modality": "CXR",
        "body_part": "CHEST",
        "model_status": "LIVE MODEL",
        "model_name": "densenet121-res224-all",
        "data_source": "LIVE MODEL INFERENCE",
        "model_explanation": "TorchXRayVision DenseNet121 model inference.",
        "model_load_ms": load_ms,
        "inference_ms": infer_ms
    })
    return result


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "web", "index.html"))


app.mount("/images", StaticFiles(directory=os.path.join(HERE, "images")), name="images")
app.mount("/web", StaticFiles(directory=os.path.join(HERE, "web")), name="web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
