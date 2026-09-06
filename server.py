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

import queue_builder
import triage

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="AURALane demo")

_model = None
_pathologies = None


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
        return queue_builder.build(os.path.join(HERE, "scores.json"))
    except FileNotFoundError:
        return JSONResponse(
            {"error": "scores.json not found — run `python prepare.py` first."},
            status_code=503)


@app.post("/api/warm")
def api_warm():
    t = time.time()
    get_model()
    return {"ok": True, "seconds": round(time.time() - t, 2)}


@app.get("/api/health")
def api_health():
    return {"model_loaded": _model is not None,
            "scores": os.path.exists(os.path.join(HERE, "scores.json"))}


@app.post("/api/score")
async def api_score(file: UploadFile = File(...)):
    """Live inference on an image the jury supplies."""
    # imported here, not at module scope: imaging pulls in torch, and the cached
    # worklist has to keep working on a machine with no torch installed at all.
    import imaging

    t0 = time.time()
    model = get_model()
    load_ms = round((time.time() - t0) * 1000)

    raw = await file.read()
    t1 = time.time()
    try:
        preds = imaging.predict(model, io.BytesIO(raw))
    except Exception as e:
        # A readable message beats "Internal Server Error" when someone hands you
        # a PDF, a DICOM, or a 3-channel screenshot mid-presentation.
        return JSONResponse(
            {"error": f"could not read {file.filename!r} as an image: {e}"},
            status_code=400)
    infer_ms = round((time.time() - t1) * 1000)

    result = triage.score(preds)
    result.update({"filename": file.filename,
                   "model_load_ms": load_ms,
                   "inference_ms": infer_ms})
    return result


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "web", "index.html"))


app.mount("/images", StaticFiles(directory=os.path.join(HERE, "images")), name="images")
app.mount("/web", StaticFiles(directory=os.path.join(HERE, "web")), name="web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
