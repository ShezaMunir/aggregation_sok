"""
icml_fetch.py -- Stage 1 retrieval for ICML, 2021-2026.

Writes one .bib per year to ICML/bib_raw/ and a manifest.

SOURCES
-------
2021-2025: PMLR, the official proceedings. Each volume publishes one BibTeX
    file with abstracts:
        https://proceedings.mlr.press/v<N>/assets/bib/bibliography.bib
    Titles and author names are LaTeX-escaped there ("Mitrovi\\'{c}") and are
    decoded to Unicode. Abstracts are not decoded (see pipeline_common).
2026: PMLR has not published the volume yet (checked 2026-09-30; latest main
    volume is v267, ICML 2025). Taken from the ICML virtual site instead, like
    ICLR: the accepted list has no abstracts, so each paper's page on icml.cc
    is fetched, title, authors and abstract are extracted, and the page is
    discarded. Progress is kept in bib_raw/icml_2026.pages.jsonl.
    Replace with the PMLR volume once it appears by adding it to PMLR_VOLUMES
    and removing 2026 from VIRTUAL_SITE_YEARS.

Main track and position-paper track are both kept, since PMLR's ICML volumes
include position papers. TMLR, JMLR and Annals of Statistics papers presented
at ICML 2026 are excluded, as are duplicate oral listings; counts go in the
manifest.

    pip install bibtexparser pandas pyyaml
    python ICML/icml_fetch.py
    python ICML/icml_fetch.py --years 2026 --limit 20   # quick check
    python covidence_prep.py ICML
"""

import os
import sys
import time
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import (  # noqa: E402
    bib_entry, clean, http_get, latex_to_text, miniconf_year, norm_title,
    parse_bib, strip_latex_commands, write_bib, write_manifest,
)

PMLR_VOLUMES = {2021: 139, 2022: 162, 2023: 202, 2024: 235, 2025: 267}
VIRTUAL_SITE_YEARS = [2026]
YEARS = sorted(PMLR_VOLUMES) + VIRTUAL_SITE_YEARS

OUTPUT_DIR = os.path.join(HERE, "bib_raw")
MANIFEST_PATH = os.path.join(HERE, "icml_fetch_manifest.csv")

# Page fetches. Each page takes about 2.3 s to serve (measured 2026-09-30), so
# 4 workers give about 1.7 requests/s; MIN_INTERVAL caps each worker if the
# site gets faster.
WORKERS = 4
MIN_INTERVAL = 0.75


def pmlr_year(year, volume, limit=None):
    url = f"https://proceedings.mlr.press/v{volume}/assets/bib/bibliography.bib"
    raw = parse_bib(text=http_get(url, timeout=180))
    papers = [e for e in raw if e["ENTRYTYPE"].lower() == "inproceedings"]

    seen, entries, n_abstract, n_dupes = set(), [], 0, 0
    for e in sorted(papers, key=lambda e: e["ID"]):
        title = latex_to_text(e.get("title", ""))
        key = norm_title(title)
        if key in seen:
            n_dupes += 1
            continue
        seen.add(key)
        abstract = strip_latex_commands(e.get("abstract", ""))
        n_abstract += int(bool(clean(abstract)))
        entries.append(bib_entry(e["ID"], [
            ("title", title),
            ("author", latex_to_text(e.get("author", ""))),
            ("year", str(year)),
            ("booktitle", latex_to_text(e.get("booktitle", ""))),
            ("volume", volume),
            ("pages", e.get("pages")),
            ("url", e.get("url")),
            ("abstract", abstract),
            ("venuekey", "icml"),
        ]))
        if limit and len(entries) >= limit:
            break

    return entries, {
        "venue": "icml", "year": year, "source": f"PMLR v{volume}",
        "listed": len(papers), "excluded_other_tracks": "",
        "listing_duplicates": n_dupes, "papers": len(entries),
        "with_abstract": n_abstract,
        "abstract_coverage": round(n_abstract / max(len(entries), 1), 4),
        "pages_fetched": 0, "page_failures": 0,
        "status": "ok" if not limit else f"TEST RUN (limit {limit})",
        "data_revision": time.strftime("%Y-%m-%d"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--years", type=int, nargs="+", default=YEARS)
    parser.add_argument("--limit", type=int, help="first N papers per year (testing)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for year in args.years:
        print(f"  ICML {year}")
        if year in PMLR_VOLUMES:
            entries, row = pmlr_year(year, PMLR_VOLUMES[year], args.limit)
        elif year in VIRTUAL_SITE_YEARS:
            entries, row = miniconf_year(
                host="icml.cc", venue="icml", year=year,
                booktitle=f"Proceedings of the International Conference on Machine Learning (ICML {year})",
                allowed_groups=[f"ICML.cc/{year}/Conference",
                                f"ICML.cc/{year}/Position_Paper_Track"],
                out_dir=OUTPUT_DIR, workers=args.workers, min_interval=MIN_INTERVAL,
                limit=args.limit,
            )
        else:
            print(f"      SKIP: no source configured for {year}")
            continue

        path = os.path.join(OUTPUT_DIR, f"icml_{year}.bib")
        write_bib(path, entries)
        print(f"      source {row['source']}: listed {row['listed']}, "
              f"excluded [{row['excluded_other_tracks'] or 'none'}], "
              f"{row['listing_duplicates']} duplicate listings")
        print(f"      -> {row['papers']} papers, {row['abstract_coverage']:.1%} with abstract, "
              f"written to {os.path.relpath(path)}")
        write_manifest(MANIFEST_PATH, [row])  # per year, so an interrupted run keeps its rows

    print(f"\nManifest: {os.path.relpath(MANIFEST_PATH)}")
    print("Next: python covidence_prep.py ICML")


if __name__ == "__main__":
    main()
