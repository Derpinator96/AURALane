"""Write the slim series index (core/series_index.py) for studies ingested before it.

    python scripts/backfill_series_index.py --stack Auralane
    python scripts/backfill_series_index.py --stack Auralane --study <uid>

For each worklist row with a datastore image set and no `series_index` in its
evidence, reads the series list and every series' instance headers from the
datastore once (the slow DICOMweb metadata calls), stores the index at
evidence/<study>/series_index.json.gz and points the row at it. After that the API
never asks the datastore for that study's metadata, even on a cold start. Rows are
otherwise untouched.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stack")
    ap.add_argument("--study")
    args = ap.parse_args()

    from core import series_index
    from core.run import load_stack, providers
    from core.types import StudyRef
    if args.stack:
        load_stack(args.stack)
    p = providers()
    table, ds, blob = p["table"], p["datastore"], p["blob"]
    rows = [r for r in table.scan("worklist") if r.get("datastore_id")
            and not (r.get("evidence") or {}).get("series_index")
            and (not args.study or r["study"] == args.study)]
    print(f"{len(rows)} studies without a series index")
    for row in rows:
        t = time.perf_counter()
        ref = StudyRef(row["study"], row["datastore_id"])
        try:
            idx = series_index.build(ds, ref, ds.get_metadata(ref))
        except Exception as e:                       # noqa: BLE001
            print(f"  {row['study'][-12:]}: skipped, {type(e).__name__}: {e}")
            continue
        key = blob.put(f"evidence/{row['study']}/series_index.json.gz", series_index.dumps(idx))
        row = table.get_item("worklist", {"study": row["study"]})
        row["evidence"] = {**(row.get("evidence") or {}), "series_index": key}
        table.put_item("worklist", row)
        n = sum(len(v) for v in idx["instances"].values())
        print(f"  {row['study'][-12:]}: {len(idx['series'])} series, {n} instances, {time.perf_counter() - t:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
