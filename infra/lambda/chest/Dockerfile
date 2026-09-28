# Chest inference image for AWS Lambda. Build context: the repository root
# (infra/auralane_stack.py sets it and excludes everything but what is copied).
#   docker build -f infra/lambda/chest/Dockerfile -t auralane-chest .
FROM public.ecr.aws/lambda/python:3.12

# CPU-only torch first, or pip pulls a multi-gigabyte CUDA build. Versions as in
# the local venv the pipeline was verified with.
RUN pip install --no-cache-dir torch==2.14.0 torchvision==0.29.0 \
        --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir "torchxrayvision==1.5.4" "grad-cam==1.5.7" "scikit-image>=0.20" \
        "pydicom>=3.0" pillow "numpy>=1.24" scipy boto3 nibabel httpx "PyJWT>=2.8" \
 # grad-cam pulls opencv-python, which needs libGL; the Lambda base has none.
 && pip uninstall -y opencv-python \
 && pip install --no-cache-dir --force-reinstall --no-deps opencv-python-headless

# Bake the DenseNet weights in; the function never downloads at run time.
ENV HOME=/opt/xrv
RUN python -c "import torchxrayvision as x; x.models.DenseNet(weights='densenet121-res224-all')"

COPY core ${LAMBDA_TASK_ROOT}/core
COPY adapters ${LAMBDA_TASK_ROOT}/adapters
COPY models ${LAMBDA_TASK_ROOT}/models
COPY imaging.py triage.py reference.json ${LAMBDA_TASK_ROOT}/
COPY infra/lambda/chest/app.py ${LAMBDA_TASK_ROOT}/chest_app.py

CMD ["chest_app.handler"]
