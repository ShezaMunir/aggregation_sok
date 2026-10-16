"""
neurips_fetch.py -- Stage 1 retrieval for NeurIPS, 2025-2026.

Writes one .bib per year to NEURIPS/bib_raw/, a manifest recording, per year,
what the source listed, what was excluded and why, and abstract coverage, and
NEURIPS/neurips_tracks.csv giving the track of every paper kept.

SOURCE
------
The NeurIPS virtual site publishes the accepted list in the same format as
ICLR's and ICML's (see ICLR/iclr_fetch.py for why OpenReview is not used):

    https://neurips.cc/static/virtual/data/neurips-<year>-orals-posters.json

The 2025 list carries abstracts. The 2026 list does not, so each paper's page
on neurips.cc is fetched and its title, authors and abstract are extracted;
bib_raw/neurips_2026.pages.jsonl keeps the extracted fields and lets an
interrupted run pick up where it stopped.

WHAT THE LIST CONTAINS
----------------------
  * Main track, Datasets and Benchmarks track (2025; renamed Evaluations and
    Datasets track in 2026), and Position Paper track: kept, each paper tagged
    with its track in neurips_tracks.csv so a track can be dropped later.
  * Papers listed again for the Mexico City satellite ("-cdmx" groups, 2025):
    collapsed with their main entry as listing duplicates.
  * TMLR, JMLR and Annals of Statistics papers in the journal track: excluded.

    python NEURIPS/neurips_fetch.py                         # both years
    python NEURIPS/neurips_fetch.py --years 2026 --limit 20  # quick check
    python covidence_prep.py NEURIPS                        # then screen
    python NEURIPS/neurips_fetch.py --tag-manifest           # add track column to included_manifest.csv
"""

import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import (  # noqa: E402
    forum_id, miniconf_list, miniconf_year, norm_title, page_url, write_bib, write_manifest,
)

YEARS = [2025, 2026]

TRACKS = {
    2025: {"Conference": "main", "Datasets_and_Benchmarks_Track": "datasets and benchmarks",
           "Position_Paper_Track": "position"},
    2026: {"Conference": "main", "Evaluations_and_Datasets_Track": "evaluations and datasets",
           "Position_Paper_Track": "position"},
}

OUTPUT_DIR = os.path.join(HERE, "bib_raw")
MANIFEST_PATH = os.path.join(HERE, "neurips_fetch_manifest.csv")
TRACKS_PATH = os.path.join(HERE, "neurips_tracks.csv")
INCLUDED_PATH = os.path.join(HERE, "included_manifest.csv")

# Same pacing as the ICLR and ICML fetchers.
WORKERS = 4
MIN_INTERVAL = 0.75


def track_of(row, year):
    source = str(row.get("sourceurl") or "")
    for group, label in TRACKS[year].items():
        if f"NeurIPS.cc/{year}/{group}" in source:
            return label
    return ""


SNAPSHOT_DIR = os.path.join(HERE, "list_snapshots")


def list_rows(year):
    """The current list plus any saved snapshots of it.

    The 2026 list changed while it was being fetched: a copy taken a day later
    no longer named about 1,700 of the papers fetched from the earlier copy.
    Snapshots in list_snapshots/ keep every row the fetch saw.
    """
    rows = list(miniconf_list("neurips.cc", "neurips", year))
    if os.path.isdir(SNAPSHOT_DIR):
        for name in sorted(os.listdir(SNAPSHOT_DIR)):
            if name.startswith(f"neurips-{year}-") and name.endswith(".json"):
                with open(os.path.join(SNAPSHOT_DIR, name), encoding="utf-8") as f:
                    data = json.load(f)
                rows += data.get("results", data) if isinstance(data, dict) else data
    return rows


def write_tracks(year):
    """Record the track of every paper key the fetcher produces for this year."""
    existing = []
    if os.path.exists(TRACKS_PATH):
        with open(TRACKS_PATH, encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f) if r["year"] != str(year)]
    rows = []
    for row in list_rows(year):
        track = track_of(row, year)
        if track:
            rows.append({"ID": f"neurips{year}-{forum_id(row) or row['id']}",
                         "year": year, "track": track,
                         "title": norm_title(row.get("name", "")),
                         "page": page_url("neurips.cc", year, row)})
    seen, unique = set(), []
    for r in existing + rows:
        if r["ID"] not in seen:
            seen.add(r["ID"])
            unique.append(r)
    with open(TRACKS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "year", "track", "title", "page"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(unique)


def tag_manifest():
    """Add a track column to included_manifest.csv, written by covidence_prep.py."""
    # The 2026 list pairs some rows with a different OpenReview id on each
    # download, so a paper's key can be missing from a later copy. Each paper's
    # page address is stable: look the track up through it, then by title.
    with open(TRACKS_PATH, encoding="utf-8") as f:
        track_rows = list(csv.DictReader(f))
    tracks = {r["ID"]: r["track"] for r in track_rows}
    by_page = {r["page"]: r["track"] for r in track_rows if r.get("page")}
    by_title = {(r["year"], r.get("title", "")): r["track"] for r in track_rows if r.get("title")}
    page_of = {}
    for name in os.listdir(OUTPUT_DIR):
        if name.endswith(".pages.jsonl"):
            with open(os.path.join(OUTPUT_DIR, name), encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    page_of[rec["key"]] = rec.get("url", "")
    with open(INCLUDED_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = [c for c in reader.fieldnames if c != "track"]
        rows = list(reader)
    fields.insert(fields.index("year") + 1, "track")
    for r in rows:
        r["track"] = (by_page.get(page_of.get(r["ID"], "")) or tracks.get(r["ID"])
                      or by_title.get((str(r["year"]), norm_title(r["title"])), ""))
    with open(INCLUDED_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    missing = sum(1 for r in rows if not r["track"])
    print(f"Tagged {len(rows)} rows in {os.path.relpath(INCLUDED_PATH)}"
          + (f"; {missing} without a track" if missing else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--years", type=int, nargs="+", default=YEARS)
    parser.add_argument("--limit", type=int, help="first N papers per year (testing)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--tag-manifest", action="store_true",
                        help="only add the track column to included_manifest.csv")
    parser.add_argument("--refresh-tracks", action="store_true",
                        help="rebuild neurips_tracks.csv from the current lists, then tag")
    args = parser.parse_args()

    if args.refresh_tracks:
        for year in args.years:
            write_tracks(year)
    if args.tag_manifest or args.refresh_tracks:
        tag_manifest()
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for year in args.years:
        print(f"  NeurIPS {year}")
        entries, row = miniconf_year(
            host="neurips.cc", venue="neurips", year=year,
            booktitle=f"Advances in Neural Information Processing Systems (NeurIPS {year})",
            allowed_groups=[f"NeurIPS.cc/{year}/{g}" for g in TRACKS[year]],
            out_dir=OUTPUT_DIR, workers=args.workers, min_interval=MIN_INTERVAL,
            limit=args.limit,
        )
        path = os.path.join(OUTPUT_DIR, f"neurips_{year}.bib")
        write_bib(path, entries)
        write_tracks(year)
        print(f"      listed {row['listed']}, excluded [{row['excluded_other_tracks'] or 'none'}], "
              f"{row['listing_duplicates']} duplicate listings")
        print(f"      -> {row['papers']} papers, {row['abstract_coverage']:.1%} with abstract, "
              f"written to {os.path.relpath(path)}")
        write_manifest(MANIFEST_PATH, [row])  # per year, so an interrupted run keeps its rows

    print(f"\nManifest: {os.path.relpath(MANIFEST_PATH)}")
    print("Next: python covidence_prep.py NEURIPS, then python NEURIPS/neurips_fetch.py --tag-manifest")


if __name__ == "__main__":
    main()
