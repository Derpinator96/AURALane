"""AURALane platform core: types, ports, registry and pipeline.

Providers live under core/providers/. Nothing outside that package imports a
provider or an AWS SDK. NOT A DIAGNOSTIC DEVICE: this orders a reading queue.
"""
import warnings

# Some public sets (the RSNA head CTs) use "ID_<hash>" for their UIDs, which are not valid DICOM UIDs.
# pydicom warns about each one every time it reads the file, hundreds of lines for one study, and the
# warning says nothing the de-identifier does not already act on: it remaps every UID. The staging script
# turns the warnings back on to count them (scripts/stage_pool.py).
warnings.filterwarnings("ignore", message="Invalid value for VR UI", category=UserWarning)
