# Head CT inference image for a SageMaker asynchronous endpoint (CPU,
# ml.m5.xlarge). Build context: the repository root. Needs the read-only clone
# of github.com/MehakGupta23/triagelane-ct at _external/triagelane-ct.
#   docker build -f infra/containers/ct/Dockerfile -t auralane-ct .
#
# Her requirements.txt is UTF-16 and pins a CUDA torch build, so it is not
# used: what her pipeline imports is listed here instead.
FROM python:3.12-slim

# Identical to the brain image's first layer, so Docker stores torch once.
RUN pip install --no-cache-dir torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
# torchvision: transformers 5 loads the ViT image processor's fast version,
# which needs it.
RUN pip install --no-cache-dir torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir "transformers>=4.46" huggingface_hub pyyaml pillow matplotlib\
        "numpy>=1.24" "pydicom>=3.0" boto3 nibabel scipy httpx "PyJWT>=2.8"

# The ViT weights, from Hugging Face at build time (about 343 MB), never at run time.
# TODO: pin a model revision here (her read-only config has revision: null).
ENV HF_HOME=/opt/hf
RUN python -c "from huggingface_hub import snapshot_download as d; \
d('DifeiT/rsna-intracranial-hemorrhage-detection', allow_patterns=['*.json', 'pytorch_model.bin'])"
ENV HF_HUB_OFFLINE=1

WORKDIR /opt/program
COPY core core
COPY adapters adapters
COPY models models
COPY imaging.py triage.py reference.json ./
COPY _external/triagelane-ct/src _external/triagelane-ct/src
COPY _external/triagelane-ct/configs _external/triagelane-ct/configs
COPY infra/containers/sagemaker_http.py sagemaker_http.py
COPY infra/containers/ct/serve.py serve.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8080
ENTRYPOINT ["python", "serve.py"]
