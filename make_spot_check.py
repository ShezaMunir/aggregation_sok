"""
make_spot_check.py -- draw a random sample of keyword-retained records per
venue for a reviewer to check against the publisher's page: is the paper from
this venue and year, and is the abstract this paper's abstract?

    python make_spot_check.py                 # 5 per venue -> spot_check_sample.csv
    python make_spot_check.py --per-venue 10
"""

import argparse
import csv
import glob
import os
import random
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
SEED = 20261016
sys.path.insert(0, REPO)
from pipeline_common import parse_bib  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--per-venue", type=int, default=5)
    parser.add_argument("--out", default="spot_check_sample.csv")
    args = parser.parse_args()

    rng = random.Random(SEED)
    rows = []
    for path in sorted(glob.glob(os.path.join(REPO, "*", "included_manifest.csv"))):
        venue = os.path.basename(os.path.dirname(path))
        with open(path, encoding="utf-8") as f:
            records = list(csv.DictReader(f))
        raw = {e["ID"]: e for bib in glob.glob(os.path.join(os.path.dirname(path), "bib_raw", "*.bib"))
               for e in parse_bib(bib)}
        if not raw:  # raw downloads not on this machine (e.g. ACL)
            print(f"  skipped {venue}: no bib_raw/")
            continue
        for r in rng.sample(records, min(args.per_venue, len(records))):
            e = raw.get(r["ID"], {})
            r = {**e, **{k: v for k, v in r.items() if v}}
            link = f"https://doi.org/{r['doi']}" if r.get("doi") else r.get("url", "")
            rows.append({
                "venue": venue, "year": r.get("year", ""), "track": r.get("track", ""),
                "title": r.get("title", ""), "link": link,
                "abstract_start": (r.get("abstract") or "")[:300],
                "right_venue_and_year": "", "abstract_is_this_paper": "", "checked_by": "", "notes": "",
            })
    out = os.path.join(REPO, args.out)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} records from {len({r['venue'] for r in rows})} venues to {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
