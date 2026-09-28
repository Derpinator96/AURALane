# Brain inference image for a SageMaker asynchronous endpoint. Build context:
# the repository root. Needs _external/brainmri with its Git LFS weights pulled
# (git lfs pull); without them the model refuses to load and every job fails.
#   docker build -f infra/containers/brain/Dockerfile -t auralane-brain .
#
# CPU image. The CUDA base (pytorch/pytorch, about 8 GB unpacked) does not fit
# the build machine's Docker disk next to the chest and CT images, and cdk
# deploy builds every image locally. The brain model runs on CPU (about 19 s
# warm on a laptop, docs/LATENCY.md), so the endpoint uses ml.m5.2xlarge.
# TODO: a CUDA image for ml.g4dn.xlarge once the Docker disk has room.
FROM python:3.12-slim

# Identical to the CT image's first layer, so Docker stores torch once.
RUN pip install --no-cache-dir torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir "monai==1.6.0" nibabel "numpy>=1.24" scipy pillow boto3 \
        "pydicom>=3.0" "scikit-image>=0.20" httpx "PyJWT>=2.8"

WORKDIR /opt/program
COPY core core
COPY adapters adapters
COPY models models
COPY imaging.py triage.py reference.json ./
COPY _external/brainmri/backend _external/brainmri/backend
COPY _external/brainmri/brats_mri_segmentation _external/brainmri/brats_mri_segmentation
COPY infra/containers/sagemaker_http.py sagemaker_http.py
COPY infra/containers/brain/serve.py serve.py

ENV PYTHONUNBUFFERED=1 OMP_NUM_THREADS=8
EXPOSE 8080
ENTRYPOINT ["python", "serve.py"]
