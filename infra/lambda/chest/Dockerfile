# Chest inference image for AWS Lambda. Build context: the repository root
# (infra/auralane_stack.py sets it and excludes everything but what is copied).
FROM public.ecr.aws/lambda/python:3.12

# CPU-only torch first, or pip pulls a multi-gigabyte CUDA build.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir "torchxrayvision>=1.5" grad-cam "scikit-image>=0.20" \
        "pydicom>=3.0" pillow "numpy>=1.24" scipy boto3 nibabel httpx "PyJWT>=2.8"

# Bake the DenseNet weights in; the function never downloads at run time.
ENV HOME=/opt/xrv
RUN python -c "import torchxrayvision as x; x.models.DenseNet(weights='densenet121-res224-all')"

COPY core ${LAMBDA_TASK_ROOT}/core
COPY adapters ${LAMBDA_TASK_ROOT}/adapters
COPY models ${LAMBDA_TASK_ROOT}/models
COPY imaging.py triage.py reference.json ${LAMBDA_TASK_ROOT}/
COPY infra/lambda/chest/app.py ${LAMBDA_TASK_ROOT}/chest_app.py

CMD ["chest_app.handler"]
