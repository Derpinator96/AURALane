# The ingest task (Fargate): one uploaded study through the whole pipeline,
# inside AWS. Started by an EventBridge rule when an upload manifest lands.
# Build context: the repository root.
#   docker build --platform linux/amd64 -f infra/containers/ingest/Dockerfile -t auralane-ingest .
#
# No torch: the models run on Lambda and SageMaker; this image de-identifies,
# imports, calls them and writes the worklist.
FROM python:3.12-slim

# Tesseract for the burned-in text search in de-identification (sim/edge/deid.py).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

# pylibjpeg-libjpeg decodes JPEG lossless (CQ500 head CT); -openjpeg, JPEG 2000.
RUN pip install --no-cache-dir "pydicom>=3.0" "numpy>=1.24" pillow pytesseract nibabel scipy \
        boto3 httpx "PyJWT>=2.8" pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg

WORKDIR /opt/program
COPY core core
COPY adapters adapters
COPY models models
COPY sim/edge sim/edge
COPY imaging.py triage.py reference.json ./

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "core.cloud_ingest"]
