"""
iclr_fetch.py -- Stage 1 retrieval for ICLR, 2021-2026.

Writes one .bib per year to ICLR/bib_raw/ and a manifest recording, per year,
what the source listed, what was excluded and why, and abstract coverage.

SOURCE
------
The design document names OpenReview as the ICLR source. Its API now answers
unauthenticated requests with 403 "Challenge verification required", and the
PDFs sit behind the same check. The ICLR virtual site publishes the accepted
list with the same titles, authors and OpenReview forum links:

    https://iclr.cc/static/virtual/data/iclr-<year>-orals-posters.json

For 2021-2025 the list carries abstracts. For 2026 it does not, so each paper's
page on iclr.cc is fetched, its title, authors and abstract are extracted, and
the page is discarded. Only the extracted fields are kept, one JSON line per
paper in bib_raw/iclr_2026.pages.jsonl, which also lets an interrupted run pick
up where it stopped.

WHAT THE LIST CONTAINS BESIDES ICLR PAPERS
------------------------------------------
  * TMLR and JMLR papers presented in the journal track: excluded. TMLR is a
    separate candidate venue in the design document (Table 7).
  * Blog-track posts (2025 on): excluded; they are not papers.
  * Orals listed twice, sometimes under placeholder forum ids such as
    "2025-Oral--4871-29ca3cc8": collapsed by normalised title, keeping the
    entry with a real OpenReview id.
Each count goes in the manifest.

    pip install bibtexparser pandas pyyaml
    python ICLR/iclr_fetch.py                        # all years
    python ICLR/iclr_fetch.py --years 2026 --limit 20  # quick check
    python covidence_prep.py ICLR                    # then screen
"""

import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import miniconf_year, write_bib, write_manifest  # noqa: E402

YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

OUTPUT_DIR = os.path.join(HERE, "bib_raw")
MANIFEST_PATH = os.path.join(HERE, "iclr_fetch_manifest.csv")

# Page fetches. Each page takes about 2.3 s to serve (measured 2026-09-30), so
# 4 workers give about 1.7 requests/s; MIN_INTERVAL caps each worker if the
# site gets faster.
WORKERS = 4
MIN_INTERVAL = 0.75


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--years", type=int, nargs="+", default=YEARS)
    parser.add_argument("--limit", type=int, help="first N papers per year (testing)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for year in args.years:
        print(f"  ICLR {year}")
        entries, row = miniconf_year(
            host="iclr.cc", venue="iclr", year=year,
            booktitle=f"International Conference on Learning Representations (ICLR {year})",
            allowed_groups=[f"ICLR.cc/{year}/Conference"],
            out_dir=OUTPUT_DIR, workers=args.workers, min_interval=MIN_INTERVAL,
            limit=args.limit,
        )
        path = os.path.join(OUTPUT_DIR, f"iclr_{year}.bib")
        write_bib(path, entries)
        print(f"      listed {row['listed']}, excluded [{row['excluded_other_tracks'] or 'none'}], "
              f"{row['listing_duplicates']} duplicate listings")
        print(f"      -> {row['papers']} papers, {row['abstract_coverage']:.1%} with abstract, "
              f"written to {os.path.relpath(path)}")
        write_manifest(MANIFEST_PATH, [row])  # per year, so an interrupted run keeps its rows

    print(f"\nManifest: {os.path.relpath(MANIFEST_PATH)}")
    print("Next: python covidence_prep.py ICLR")


if __name__ == "__main__":
    main()
