"""
aamas_fetch.py -- Stage 1 retrieval for AAMAS (International Joint Conference
on Autonomous Agents and Multiagent Systems), 2021-2026.

2021-2025: Crossref. IFAAMAS registers AAMAS papers under their own DOI prefix
(10.65109), with abstracts. The proceedings hold full papers (about 9 pages)
and extended abstracts (about 3 pages); both are kept, and the page range in
each record tells them apart.

2026: the proceedings are on the IFAAMAS site, and their DOIs are registered
but carry no publication date, so a date filter on Crossref misses them. The
paper list comes from the IFAAMAS table of contents, which gives each paper's
title, authors, page and track; a paper's PDF is named after its DOI suffix
(IREH8205.pdf -> 10.65109/ireh8205). Abstracts come by DOI from Crossref,
OpenAlex and Semantic Scholar, and otherwise from the first page of the PDF,
which is read in memory and discarded. Keynote talks are removed. Every paper's
track goes in aamas_tracks.csv; AAAI- and JAAMAS-track papers are presented at
AAMAS but published elsewhere, so they can be filtered there.

    python AAMAS/aamas_fetch.py                  # 2021-2026
    python AAMAS/aamas_fetch.py --years 2026     # IFAAMAS part only
    python covidence_prep.py AAMAS
    python AAMAS/aamas_fetch.py --tag-manifest   # add the track column (2026 rows)
"""

import argparse
import csv
import html
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import (  # noqa: E402
    CROSSREF_API, CROSSREF_MAILTO, USER_AGENT, bib_entry, clean, http_get, http_get_json,
    openalex_abstracts, run_crossref_venue, semanticscholar_abstracts, strip_jats,
    write_bib, write_manifest,
)

CROSSREF_YEARS = list(range(2021, 2026))
CONTENTS_URL = "https://www.ifaamas.org/Proceedings/aamas{year}/forms/contents.htm"
PDF_URL = "https://www.ifaamas.org/Proceedings/aamas{year}/pdfs/{name}.pdf"
NAME = "International Joint Conference on Autonomous Agents and Multiagent Systems"
DROP_TRACKS = {"Keynote Talks"}
TRACKS_PATH = os.path.join(HERE, "aamas_tracks.csv")
INCLUDED_PATH = os.path.join(HERE, "included_manifest.csv")
MANIFEST_PATH = os.path.join(HERE, "aamas_fetch_manifest.csv")
PDF_INTERVAL = 1.0

ENTRY_RE = re.compile(
    r'<a name="([^"]+)"[^>]*></a>\s*<font[^>]*>([^<]+)</font>'                 # track heading
    r'|<a href="\.\./pdfs/([A-Z]{4}\d{4})\.pdf"[^>]*>\s*<font[^>]*>\s*<strong>(.*?)</strong>'
    r'(.*?)</p>', re.S)


def is_aamas(item):
    return "autonomous agents and multiagent systems" in " ".join(item.get("container-title") or []).lower()


def contents(year):
    """[(pdf name, title, authors, page, track)] from the IFAAMAS table of contents."""
    page = http_get(CONTENTS_URL.format(year=year), timeout=120)
    track, papers = "", []
    for m in ENTRY_RE.finditer(page):
        if m.group(1):
            track = " ".join(html.unescape(m.group(2)).split())
            continue
        rest = m.group(5)
        number = re.search(r"\(Page (\d+)\)", rest)
        names = [clean(html.unescape(re.sub(r"<[^>]+>", "", a)))
                 for a in re.split(r"<br>", re.sub(r"<i>.*?</i>", "", rest, flags=re.S))[1:]]
        papers.append((m.group(3), clean(html.unescape(re.sub(r"<[^>]+>", "", m.group(4)))),
                       [n for n in names if n], number.group(1) if number else "", track))
    return papers


def crossref_abstracts(dois, batch=40):
    out = {}
    for i in range(0, len(dois), batch):
        flt = ",".join(f"doi:{d}" for d in dois[i:i + batch])
        params = {"filter": flt, "rows": batch, "select": "DOI,abstract", "mailto": CROSSREF_MAILTO}
        for item in http_get_json(CROSSREF_API + "?" + urllib.parse.urlencode(params))["message"]["items"]:
            text = strip_jats(item.get("abstract"))
            if len(text.split()) >= 30:
                out[item["DOI"].lower()] = text
        time.sleep(0.2)
    return out


def pdf_abstract(year, name):
    """The abstract from the first page of a paper's PDF, or None on failure."""
    from pypdf import PdfReader
    request = urllib.request.Request(PDF_URL.format(year=year, name=name), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            reader = PdfReader(io.BytesIO(response.read()))
        text = " ".join((reader.pages[0].extract_text() or "").split())
    except Exception:
        return None
    match = re.search(r"\bABSTRACT\b\s*(.+?)(?=\bCCS CONCEPTS\b|\bKEYWORDS\b|\bACM Reference Format\b"
                      r"|\b1\s+INTRODUCTION\b|$)", text, re.S)  # case-sensitive: "Extended Abstract" heads the page
    abstract = clean(match.group(1)) if match else ""
    abstract = re.sub(r"(\w)- (\w)", r"\1\2", abstract)  # rejoin words hyphenated at line ends
    return abstract if len(abstract.split()) >= 30 else ""


def fetch_from_contents(year):
    papers = contents(year)
    kept = [p for p in papers if p[4] not in DROP_TRACKS]
    dropped = len(papers) - len(kept)
    print(f"  AAMAS {year} (IFAAMAS): {len(papers)} listed, {dropped} keynote talks removed")
    doi = {p[0]: f"10.65109/{p[0].lower()}" for p in kept}
    abstracts, source = {}, {}
    for label, getter in (("crossref", crossref_abstracts), ("openalex", openalex_abstracts),
                          ("semantic scholar", semanticscholar_abstracts)):
        missing = [d for d in doi.values() if d not in abstracts]
        for d, text in getter(missing).items():
            if d in doi.values() and d not in abstracts and len(text.split()) >= 30:
                abstracts[d], source[d] = text, label
        print(f"      after {label}: {len(abstracts)} of {len(kept)} with abstract")
    progress = os.path.join(HERE, "bib_raw", f"aamas_{year}.pdf_abstracts.jsonl")
    done = {}
    if os.path.exists(progress):
        with open(progress, encoding="utf-8") as f:
            done = {r["doi"]: r["abstract"] for r in map(json.loads, f)}
    todo = [(name, d) for name, d in doi.items() if d not in abstracts and d not in done]
    os.makedirs(os.path.dirname(progress), exist_ok=True)
    failures = 0
    with open(progress, "a", encoding="utf-8") as f:
        for i, (name, d) in enumerate(todo, 1):
            text = pdf_abstract(year, name)
            failures += text is None
            f.write(json.dumps({"doi": d, "abstract": text or ""}) + "\n")
            done[d] = text or ""
            if i % 25 == 0 or i == len(todo):
                print(f"      PDFs read: {i}/{len(todo)}")
            time.sleep(PDF_INTERVAL)
    for d, text in done.items():
        if d not in abstracts and text:
            abstracts[d], source[d] = text, "pdf"

    entries, tracks = [], []
    for name, title, authors, page, track in kept:
        d = doi[name]
        key = f"aamas{year}-{name.lower()}"
        entries.append(bib_entry(key, [
            ("title", title), ("author", " and ".join(authors)), ("year", str(year)),
            ("booktitle", NAME), ("pages", page), ("doi", d), ("url", f"https://doi.org/{d}"),
            ("abstract", abstracts.get(d, "")), ("abstractsource", source.get(d, "")),
            ("section", track), ("venuekey", "aamas"),
        ]))
        tracks.append({"ID": key, "year": year, "track": track})
    write_bib(os.path.join(HERE, "bib_raw", f"aamas_{year}.bib"), entries)
    with open(TRACKS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "year", "track"])
        writer.writeheader()
        writer.writerows(tracks)
    n_abs = sum(1 for k in kept if doi[k[0]] in abstracts)
    counts = {}
    for s in source.values():
        counts[s] = counts.get(s, 0) + 1
    row = {"venue": "aamas", "year": year, "source": "IFAAMAS table of contents",
           "listed": len(papers), "excluded_other_tracks": f"Keynote Talks: {dropped}" if dropped else "",
           "listing_duplicates": 0, "papers": len(kept), "with_abstract": n_abs,
           "abstract_coverage": round(n_abs / max(len(kept), 1), 4),
           "pages_fetched": len(todo), "page_failures": failures, "status": "ok",
           "data_revision": time.strftime("%Y-%m-%d"),
           "note": "abstracts: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))}
    write_manifest(MANIFEST_PATH, [row])
    print(f"      -> {len(kept)} papers, {row['abstract_coverage']:.1%} with abstract ({row['note']})")


def tag_manifest():
    with open(TRACKS_PATH, encoding="utf-8") as f:
        tracks = {r["ID"]: r["track"] for r in csv.DictReader(f)}
    with open(INCLUDED_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = [c for c in reader.fieldnames if c != "track"]
        rows = list(reader)
    fields.insert(fields.index("year") + 1, "track")
    for r in rows:
        r["track"] = tracks.get(r["ID"], "")
    with open(INCLUDED_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Tagged {sum(1 for r in rows if r['track'])} of {len(rows)} rows with a track (2026 only)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--years", type=int, nargs="+", default=CROSSREF_YEARS + [2026])
    parser.add_argument("--tag-manifest", action="store_true")
    args = parser.parse_args()
    if args.tag_manifest:
        tag_manifest()
        return
    crossref_years = [y for y in args.years if y in CROSSREF_YEARS]
    if crossref_years:
        run_crossref_venue(
            HERE, "aamas", f"AAMAS {min(crossref_years)}-{max(crossref_years)} (Crossref)", NAME,
            {"prefix": "10.65109", "from-pub-date": f"{min(crossref_years)}-01-01",
             "until-pub-date": f"{max(crossref_years)}-12-31"},
            crossref_years, entry_type="inproceedings", keep=is_aamas)
    for year in args.years:
        if year not in CROSSREF_YEARS:
            fetch_from_contents(year)


if __name__ == "__main__":
    main()
