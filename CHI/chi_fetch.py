"""
chi_fetch.py -- Stage 1 retrieval for CHI full papers, 2021-2026.

CHI is not in the design document's Table 7 candidate list. It was added on
2026-09-30; record the amendment and its stratum in the protocol.

Writes one .bib per year to CHI/bib_raw/ and a manifest.

SOURCES
-------
2021-2025: the ACM DL BibTeX exports made for the earlier annotation SoK,
    reference_code/paper_parsing/chi/chi_<year>*.bib, which carry abstracts and
    author keywords. ACM writes HTML entities into them (&nbsp;, &amp;), which
    are decoded. ACM caps an export at 1,000 records, so 2024 and 2025 were
    exported in two parts that overlap; the overlap is removed by DOI. Their
    URLs go through the UofT library proxy and are rewritten to doi.org.
2026: the SIGCHI conference program (programs.sigchi.org/chi/2026), whose data
    file lists every accepted full paper with title, authors, abstract and ACM
    DOI. ACM DL refuses scripted requests (403) and Crossref carries no ACM
    abstracts. The program has no author keywords, so CHI 2026 is screened on
    title and abstract only, while 2021-2025 also use keywords.

Only the "Paper" content type is kept from the program: posters, late-breaking
work, workshops, demos, panels and TOCHI journal presentations are not CHI
proceedings papers.

    pip install bibtexparser pandas pyyaml
    python CHI/chi_fetch.py
    python covidence_prep.py CHI
"""

import os
import re
import sys
import glob
import html
import time
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, REPO_ROOT)

from pipeline_common import (  # noqa: E402
    bib_entry, clean, http_get_json, latex_to_text, parse_bib, write_bib,
    write_manifest,
)

EXPORT_YEARS = [2021, 2022, 2023, 2024, 2025]
EXPORT_DIR = os.path.join(REPO_ROOT, "reference_code", "paper_parsing", "chi")

# SIGCHI program data. 10142 is CHI 2026's conference id on programs.sigchi.org;
# the program file is versioned, and the current version is looked up first.
PROGRAM_YEARS = {2026: 10142}
PROGRAM_BASE = "https://files.sigchi.org/conference/cache"

YEARS = EXPORT_YEARS + sorted(PROGRAM_YEARS)

OUTPUT_DIR = os.path.join(HERE, "bib_raw")
MANIFEST_PATH = os.path.join(HERE, "chi_fetch_manifest.csv")


def booktitle(year):
    return f"Proceedings of the {year} CHI Conference on Human Factors in Computing Systems"


def manifest_row(year, source, listed, n_dupes, entries, n_abstract, revision, note=""):
    return {
        "venue": "chi", "year": year, "source": source, "listed": listed,
        "excluded_other_tracks": "", "listing_duplicates": n_dupes,
        "papers": len(entries), "with_abstract": n_abstract,
        "abstract_coverage": round(n_abstract / max(len(entries), 1), 4),
        "pages_fetched": 0, "page_failures": 0, "status": "ok",
        "data_revision": revision, "note": note,
    }


def export_year(year):
    files = sorted(glob.glob(os.path.join(EXPORT_DIR, f"chi_{year}*.bib")))
    if not files:
        raise SystemExit(f"No ACM export for CHI {year} in {EXPORT_DIR}")
    raw = [e for path in files for e in parse_bib(path)]

    seen, entries, n_abstract = set(), [], 0
    for e in raw:
        doi = clean(e.get("doi")).lower()
        key = doi or clean(e.get("title")).lower()
        if key in seen:
            continue
        seen.add(key)
        abstract = html.unescape(e.get("abstract", ""))
        n_abstract += int(bool(clean(abstract)))
        entries.append(bib_entry(e["ID"], [
            ("title", html.unescape(latex_to_text(e.get("title", "")))),
            ("author", latex_to_text(e.get("author", ""))),
            ("year", str(year)),
            ("booktitle", booktitle(year)),
            ("doi", doi),
            ("url", f"https://doi.org/{doi}" if doi else ""),
            ("abstract", abstract),
            ("keywords", html.unescape(e.get("keywords", ""))),
            ("venuekey", "chi"),
        ]))

    names = ", ".join(os.path.basename(p) for p in files)
    return entries, manifest_row(
        year, f"ACM DL export ({names})", len(raw), len(raw) - len(entries),
        entries, n_abstract, "earlier-SoK export",
        note="overlap between split exports removed by DOI" if len(files) > 1 else "",
    )


def program_year(year, conference_id):
    version = http_get_json(f"{PROGRAM_BASE}/{conference_id}/version-2")["scheduleVersion"]
    data = http_get_json(f"{PROGRAM_BASE}/{conference_id}/{version}/program")

    type_ids = {t["id"] for t in data["contentTypes"] if t["name"] == "Paper"}
    people = {p["id"]: p for p in data["people"]}

    def author_name(person_id):
        p = people.get(person_id, {})
        first = " ".join(x for x in (p.get("firstName"), p.get("middleInitial")) if x)
        last = p.get("lastName", "")
        return f"{last}, {first}" if last and first else (last or first)

    listed = [c for c in data["contents"] if c["typeId"] in type_ids]
    seen, entries, n_abstract = set(), [], 0
    for c in sorted(listed, key=lambda c: c["id"]):
        doi_url = ((c.get("addons") or {}).get("doi") or {}).get("url", "")
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi_url).lower()
        key = doi or clean(c.get("title")).lower()
        if key in seen:
            continue
        seen.add(key)
        abstract = c.get("abstract", "")
        n_abstract += int(bool(clean(abstract)))
        entries.append(bib_entry(doi or f"chi{year}-{c['id']}", [
            ("title", c.get("title")),
            ("author", " and ".join(author_name(a["personId"]) for a in c.get("authors", []))),
            ("year", str(year)),
            ("booktitle", booktitle(year)),
            ("doi", doi),
            ("url", doi_url or f"https://programs.sigchi.org/chi/{year}/program/content/{c['id']}"),
            ("abstract", abstract),
            ("venuekey", "chi"),
        ]))

    return entries, manifest_row(
        year, "SIGCHI program (programs.sigchi.org)", len(listed),
        len(listed) - len(entries), entries, n_abstract,
        f"program v{version}, {time.strftime('%Y-%m-%d')}",
        note="no author keywords in source; screened on title and abstract",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--years", type=int, nargs="+", default=YEARS)
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for year in args.years:
        print(f"  CHI {year}")
        if year in EXPORT_YEARS:
            entries, row = export_year(year)
        elif year in PROGRAM_YEARS:
            entries, row = program_year(year, PROGRAM_YEARS[year])
        else:
            print(f"      SKIP: no source configured for {year}")
            continue
        path = os.path.join(OUTPUT_DIR, f"chi_{year}.bib")
        write_bib(path, entries)
        print(f"      source {row['source']}: listed {row['listed']}, "
              f"{row['listing_duplicates']} duplicates removed")
        print(f"      -> {row['papers']} papers, {row['abstract_coverage']:.1%} with abstract, "
              f"written to {os.path.relpath(path)}")
        write_manifest(MANIFEST_PATH, [row])  # per year, so an interrupted run keeps its rows

    print(f"\nManifest: {os.path.relpath(MANIFEST_PATH)}")
    print("Next: python covidence_prep.py CHI")


if __name__ == "__main__":
    main()
