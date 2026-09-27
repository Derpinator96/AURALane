# Brain inference image for a SageMaker asynchronous endpoint (GPU,
# ml.g4dn.xlarge). Build context: the repository root. Needs
# _external/brainmri with its Git LFS weights pulled (git lfs pull); without
# them the model refuses to load and every job fails loudly.
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

RUN pip install --no-cache-dir "monai>=1.3" nibabel "numpy>=1.24" scipy pillow boto3 \
        "pydicom>=3.0" "scikit-image>=0.20" httpx "PyJWT>=2.8"

WORKDIR /opt/program
COPY core core
COPY adapters adapters
COPY models models
COPY imaging.py triage.py reference.json ./
COPY _external/brainmri _external/brainmri
COPY infra/containers/brain/serve.py serve.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8080
ENTRYPOINT ["python", "serve.py"]
