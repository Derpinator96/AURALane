"""A slim series and instance index for the viewer.

The viewer needs, per instance, the DICOM header elements Cornerstone decodes a
frame with (size, bit depth, photometric interpretation, spacing, position,
window, rescale, transfer syntax) and nothing else. HealthImaging answers that
through DICOMweb series metadata, a request of several seconds for a brain MR.
At ingest the pipeline writes this index to S3 (evidence/<study>/series_index.json.gz)
so an API instance with a cold cache never asks DICOMweb for it, and the API
keeps what it reads in memory: an imported image set does not change.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import gzip
import json
from typing import Any

# DICOM tags kept per instance, as DICOM JSON keys.
KEEP = frozenset("""
00020010 00080005 00080008 00080016 00080018 00080060 0008103E
00180050 00180088 00181164 00185101
0020000D 0020000E 00200011 00200013 00200032 00200037 00200052 00201041
00280002 00280004 00280006 00280008 00280010 00280011 00280030 00280034
00280100 00280101 00280102 00280103 00280106 00280107
00281050 00281051 00281052 00281053 00281054 00282110
""".split())


def slim(item: dict) -> dict:
    return {t: v for t, v in item.items() if t in KEEP}


def build(datastore, ref, meta) -> dict[str, Any]:
    """{"series": [...], "instances": {series_uid: [slim header, ...]}} for a study."""
    series = [{"series_uid": s.series_uid, "number": s.number, "description": s.description,
               "instance_count": s.instance_count, "instance_uids": list(s.instance_uids)}
              for s in meta.series]
    instances = {s["series_uid"]: [slim(i) for i in datastore.series_metadata(ref, s["series_uid"])]
                 for s in series}
    return {"series": series, "instances": instances}


def dumps(index: dict) -> bytes:
    return gzip.compress(json.dumps(index, separators=(",", ":")).encode())


def loads(data: bytes) -> dict:
    return json.loads(gzip.decompress(data))
