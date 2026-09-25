# Setup: clean Windows machine to a green doctor

Commands run from the repo root in PowerShell unless noted.

## Prerequisites (docs/MANUAL-STEPS.md has the detail)

1. Python 3.11 or newer. This build uses 3.14.
2. Node 20 or newer: `winget install OpenJS.NodeJS.LTS`
3. Docker Desktop with the WSL 2 engine: `winget install Docker.DockerDesktop`
4. Tesseract, then add `C:\Program Files\Tesseract-OCR` to the user PATH:
   `winget install UB-Mannheim.TesseractOCR`
5. AWS CLI, then `aws configure` with region `us-east-1`:
   `winget install Amazon.AWSCLI`
6. Open a new terminal, or refresh PATH in the current one:
   `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`

## Code and Python

7. `git clone https://github.com/Derpinator96/AURALane.git; cd AURALane`
8. `python -m venv .venv; .venv\Scripts\activate`
9. `pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`
   (first, or pip pulls a ~2.5 GB CUDA build)
10. `pip install -r requirements.txt`
11. `pip install -r requirements-dev.txt`

## Data (none of it is in git)

12. NIH ChestX-ray14 sample PNGs into `images\` (Kaggle `nih-chest-xrays/sample`).
13. BraTS 2021 cases into `data\brain\raw\<case>\<case>_{t1,t1ce,t2,flair,seg}.nii.gz`.
14. Brain model, read-only:
    `git clone https://github.com/shauryajain111/brainmri.git _external\brainmri`
15. `python data\chest\make_chest_corpus.py` (40 chest studies, exit 0 only if OCR agrees)
16. `python data\brain\nifti_to_dicom.py --slices 1` (all 155 slices, the volume the model sees)

## Local stack

17. `docker compose -f docker-compose.local.yml up -d`
    Orthanc on 8042, DynamoDB Local on 8001. Port 8000 stays free for the demo.

    Both services restart by themselves (`restart: unless-stopped`) and keep
    their data until the containers are removed.

**Reset Orthanc after any change to de-identification.** Orthanc does not
overwrite an instance it already holds, and the identity map gives a
re-ingested study the same pseudonymous UIDs, so a study stored under old
de-identification rules keeps its old metadata. This has already bitten once:
brain studies stored before sequence names were kept still read
`TRIAGE SERIES`, and the pipeline then refuses them as unidentifiable. Before
measuring or re-testing, clear the stack (neither service has a volume, so
removing the containers deletes everything in both stores):

    docker compose -f docker-compose.local.yml down
    docker compose -f docker-compose.local.yml up -d

## Check

18. `python scripts\doctor.py` must print `all green`.
19. `python scripts\orthanc_roundtrip.py` must print `12/12 checks passed`.
20. `pytest sim\edge\test_deid.py sim\generator\test_make_dicom.py data\brain\test_nifti_to_dicom.py -v`

## Round-2 demo (the fallback)

21. `python server.py`, then http://localhost:8000. Runs alongside the stack.
