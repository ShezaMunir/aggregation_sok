"""
pipeline_common.py -- helpers shared by the venue fetchers and covidence_prep.py.

Fetchers (Stage 1) write raw .bib and a manifest; covidence_prep.py (Stage 2)
screens that .bib. Neither screens inside retrieval. Keeping the .bib fields and
manifest columns in one place means every venue reaches Stage 2 in the same
shape, whatever the upstream source looked like.

ACL/acl_fetch.py predates this module and stays self-contained.
"""

import os
import re
import csv
import json
import html
import time
import random
import threading
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import bibtexparser

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

USER_AGENT = ("Mozilla/5.0 (compatible; aggregation-sok-retrieval/1.0; "
              "academic systematic review)")

MANIFEST_FIELDS = [
    "venue", "year", "source", "listed", "excluded_other_tracks",
    "listing_duplicates", "papers", "with_abstract", "abstract_coverage",
    "pages_fetched", "page_failures", "status", "data_revision", "note",
]


# ----------------------------------------------------------------------------
# Text
# ----------------------------------------------------------------------------

def clean(text):
    """Collapse whitespace and drop braces so a value round-trips through BibTeX."""
    if text is None:
        return ""
    text = str(text)
    if text.lower() in ("nan", "none"):
        return ""
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def norm_title(title):
    if not isinstance(title, str):
        return ""
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


try:
    from pylatexenc.latex2text import LatexNodes2Text
    _LATEX = LatexNodes2Text()
except ImportError:  # bibtexparser v1 installs do not pull in pylatexenc
    _LATEX = None


def latex_to_text(text):
    """Decode LaTeX accents in short fields (titles, author names).

    Not applied to abstracts: LaTeX treats a bare % as a comment, so decoding
    "50% of participants ..." would silently drop the rest of the abstract.
    """
    if not text or _LATEX is None or ("\\" not in text and "$" not in text):
        return text
    try:
        return _LATEX.latex_to_text(text)
    except Exception:
        return text


def strip_latex_commands(text):
    r"""Turn \emph{social choice} into ' social choice' so \b-anchored patterns
    still match. Math and bare commands are left alone."""
    return re.sub(r"\\[a-zA-Z]+\*?\s*(?=\{)", " ", text or "")


# ----------------------------------------------------------------------------
# BibTeX
# ----------------------------------------------------------------------------

BIBTEX_V1 = hasattr(bibtexparser, "bparser")


def parse_bib(path=None, text=None):
    """Return a list of dicts with lowercase field names plus ENTRYTYPE and ID.

    bibtexparser v1 and v2 have incompatible APIs and both are in the wild;
    `pip install bibtexparser` now gives v2. Support both.
    """
    if text is None:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

    if BIBTEX_V1:
        from bibtexparser.bparser import BibTexParser
        db = bibtexparser.loads(text, parser=BibTexParser(common_strings=True))
        return list(db.entries)

    library = bibtexparser.parse_string(text)
    if library.failed_blocks:
        # v2 drops these silently, which would quietly change PRISMA counts
        kinds = Counter(type(b).__name__ for b in library.failed_blocks)
        print(f"  WARNING: {len(library.failed_blocks)} BibTeX blocks in "
              f"{os.path.basename(path) if path else 'input'} were not parsed "
              f"({', '.join(f'{k}: {n}' for k, n in kinds.items())})")
    entries = []
    for entry in library.entries:
        record = {f.key.lower(): f.value for f in entry.fields}
        record["ENTRYTYPE"] = entry.entry_type
        record["ID"] = entry.key
        entries.append(record)
    return entries


def bib_entry(key, fields, entry_type="inproceedings"):
    """fields: list of (name, value). Empty values are omitted."""
    lines = [f"@{entry_type}{{{key},"]
    lines += [f"  {k} = {{{clean(v)}}}," for k, v in fields if clean(v)]
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def write_bib(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(entries) + "\n")


def write_manifest(path, rows):
    """Merge rows into the manifest, replacing earlier rows for the same
    venue-year, so fetching one year does not erase the others."""
    merged = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                merged[(row["venue"], str(row["year"]))] = row
    for row in rows:
        merged[(row["venue"], str(row["year"]))] = row
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged[k] for k in sorted(merged))


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------

RETRY_STATUS = (429, 500, 502, 503, 504)


def http_get(url, timeout=60, retries=4, backoff=2.0):
    last = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUS:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(backoff * 2 ** attempt + random.random())
    raise last


def http_get_json(url, retries=3):
    """Large JSON files occasionally arrive truncated; refetch on a parse error."""
    for attempt in range(retries + 1):
        try:
            return json.loads(http_get(url, timeout=180))
        except json.JSONDecodeError:
            if attempt == retries:
                raise
            time.sleep(5)


# ----------------------------------------------------------------------------
# Conference virtual sites (iclr.cc, icml.cc)
# ----------------------------------------------------------------------------
# ICLR and ICML publish their accepted-paper list as
#   https://<host>/static/virtual/data/<venue>-<year>-orals-posters.json
# and a page per paper at https://<host>/virtual/<year>/poster/<id>.

FORUM_RE = re.compile(r"openreview\.net/forum\?id=([^&\s\"']+)")
PLACEHOLDER_ID_RE = re.compile(r"^\d{4}-Oral--")


def miniconf_list(host, venue, year):
    url = f"https://{host}/static/virtual/data/{venue}-{year}-orals-posters.json"
    data = http_get_json(url)
    return data.get("results", data) if isinstance(data, dict) else data


def forum_id(row):
    """OpenReview forum id, ignoring the placeholder ids some oral entries carry."""
    for key in ("paper_url", "paper_pdf_url"):
        match = FORUM_RE.search(str(row.get(key) or ""))
        if match and not PLACEHOLDER_ID_RE.match(match.group(1)):
            return match.group(1)
    return ""


def _track_label(source):
    if "TMLR" in source:
        return "TMLR journal track"
    if "Jmlr" in source or "JMLR" in source:
        return "JMLR journal track"
    if "BlogPosts" in source:
        return "blog track"
    return source[:60] or "no source"


def select_papers(rows, allowed_groups):
    """Keep each of the conference's own papers once.

    A row is the conference's own when its sourceurl names one of
    allowed_groups (e.g. "ICLR.cc/2025/Conference"). Rows with no sourceurl
    (all of ICLR 2021) are kept when they carry an OpenReview forum link.
    Orals are often listed twice, once as a poster; duplicates are collapsed by
    normalised title, preferring the entry with a real forum id.

    Returns (kept_rows, excluded_counter, n_duplicates).
    """
    excluded = Counter()
    candidates = []
    for row in rows:
        source = str(row.get("sourceurl") or "")
        if source in ("", "None"):
            if not forum_id(row):
                excluded["no source"] += 1
                continue
        elif not any(group in source for group in allowed_groups):
            excluded[_track_label(source)] += 1
            continue
        candidates.append(row)

    def rank(row):
        return (bool(forum_id(row)), row.get("eventtype") == "Poster",
                bool(str(row.get("abstract") or "").strip()))

    # Collapse by title, then by forum id: some papers are listed twice under
    # slightly different names but the same OpenReview id (15 at ICML 2026).
    best = {}
    for row in candidates:
        key = norm_title(row.get("name", ""))
        if key not in best or rank(row) > rank(best[key]):
            best[key] = row
    by_forum = {}
    for row in best.values():
        key = forum_id(row) or f"no-forum-{row['id']}"
        if key not in by_forum or rank(row) > rank(by_forum[key]):
            by_forum[key] = row
    kept = list(by_forum.values())
    return kept, excluded, len(candidates) - len(kept)


def page_url(host, year, row):
    path = row.get("virtualsite_url")
    if path and path != "None":
        return f"https://{host}{path}"
    return f"https://{host}/virtual/{year}/{str(row.get('eventtype', 'poster')).lower()}/{row['id']}"


def _grab(page, pattern):
    match = re.search(pattern, page, re.S)
    if not match:
        return ""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())


def parse_event_page(page):
    authors = _grab(page, r'<div class="event-organizers">(.*?)</div>')
    link = re.search(r'href="(https://openreview\.net/forum\?id=[^"]+)"', page)
    return {
        "title": _grab(page, r'<h1 class="event-title">(.*?)</h1>'),
        "authors": [a.strip() for a in authors.split("\u22c5") if a.strip()],
        "abstract": _grab(page, r'<div class="abstract-text-inner">(.*?)</div>'),
        "openreview": link.group(1) if link else "",
    }


def fetch_pages(jobs, progress_path, workers=2, min_interval=0.75, label=""):
    """Fetch each paper page, extract its fields, and discard the page.

    jobs: list of (key, url). Nothing but the extracted fields is kept: each
    page is parsed in memory and dropped, and the fields are appended to
    progress_path as one JSON line per paper. A rerun skips keys already done
    and retries keys that failed.

    Each worker waits at least min_interval seconds between its requests, so
    the host sees at most workers / min_interval requests per second.
    """
    done = {}
    if os.path.exists(progress_path):
        with open(progress_path, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # blank, or cut short when a run was interrupted
                done[record["key"]] = record  # later lines supersede earlier

    todo = [(k, u) for k, u in jobs if k not in done or done[k].get("error")]
    if not todo:
        return done
    if os.path.exists(progress_path) and os.path.getsize(progress_path):
        with open(progress_path, "rb+") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")  # finish a line cut short by an interruption
    print(f"      fetching {len(todo)} pages{label} "
          f"({len(jobs) - len(todo)} already done, {workers} workers)")

    lock = threading.Lock()
    counter = {"n": 0, "failed": 0}
    started = time.monotonic()

    def work(job):
        key, url = job
        t0 = time.monotonic()
        try:
            page = http_get(url, timeout=60)
            record = {"key": key, "url": url, **parse_event_page(page)}
            del page
            if not record["abstract"]:
                record["error"] = "no abstract on page"
        except Exception as exc:
            record = {"key": key, "url": url, "error": f"{type(exc).__name__}: {exc}"[:200]}
        with lock:
            with open(progress_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            done[key] = record
            counter["n"] += 1
            counter["failed"] += int(bool(record.get("error")))
            if counter["n"] % 250 == 0 or counter["n"] == len(todo):
                rate = counter["n"] / max(time.monotonic() - started, 1e-9)
                eta = (len(todo) - counter["n"]) / max(rate, 1e-9) / 60
                print(f"        {counter['n']}/{len(todo)} pages, "
                      f"{counter['failed']} failed, {rate:.1f}/s, ~{eta:.0f} min left",
                      flush=True)
        time.sleep(max(0.0, min_interval - (time.monotonic() - t0)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, todo))
    return done


def authors_from_row(row):
    authors = row.get("authors") or []
    return [clean(a.get("fullname")) for a in authors if isinstance(a, dict) and a.get("fullname")]


def keywords_from_row(row):
    keywords = row.get("keywords") or []
    if isinstance(keywords, list):
        return ", ".join(clean(k) for k in keywords if clean(k))
    return clean(keywords)


def miniconf_year(host, venue, year, booktitle, allowed_groups, out_dir,
                  workers=2, min_interval=0.75, limit=None):
    """Retrieve one venue-year from a conference virtual site.

    Abstracts come from the list where it has them. Where it does not (ICLR and
    ICML 2026, a few ICLR 2024 papers), the paper's own page is fetched.
    Returns (bib entries, manifest row).
    """
    rows = miniconf_list(host, venue, year)
    kept, excluded, n_dupes = select_papers(rows, allowed_groups)
    kept.sort(key=lambda r: norm_title(r.get("name", "")))
    if limit:
        kept = kept[:limit]

    def key_for(row):
        return f"{venue}{year}-{forum_id(row) or row['id']}"

    need_page = [(key_for(r), page_url(host, year, r)) for r in kept
                 if not str(r.get("abstract") or "").strip()]
    pages = {}
    if need_page:
        progress = os.path.join(out_dir, f"{venue}_{year}.pages.jsonl")
        pages = fetch_pages(need_page, progress, workers, min_interval,
                            label=f" from {host}")

    entries, n_abstract, n_failed = [], 0, 0
    for row in kept:
        key = key_for(row)
        page = pages.get(key, {})
        if page.get("error"):
            n_failed += 1
        title = page.get("title") or row.get("name")
        authors = page.get("authors") or authors_from_row(row)
        abstract = page.get("abstract") or row.get("abstract")
        fid = forum_id(row)
        url = f"https://openreview.net/forum?id={fid}" if fid else (page.get("openreview") or page_url(host, year, row))
        n_abstract += int(bool(clean(abstract)))
        entries.append(bib_entry(key, [
            ("title", title),
            ("author", " and ".join(clean(a) for a in authors)),
            ("year", str(year)),
            ("booktitle", booktitle),
            ("url", url),
            ("abstract", abstract),
            ("keywords", keywords_from_row(row)),
            ("eventurl", page_url(host, year, row)),
            ("decision", row.get("decision")),
            ("venuekey", venue),
        ]))

    manifest = {
        "venue": venue, "year": year, "source": f"{host} virtual site",
        "listed": len(rows),
        "excluded_other_tracks": "; ".join(f"{k}: {v}" for k, v in excluded.most_common()),
        "listing_duplicates": n_dupes,
        "papers": len(entries), "with_abstract": n_abstract,
        "abstract_coverage": round(n_abstract / max(len(entries), 1), 4),
        "pages_fetched": len(need_page), "page_failures": n_failed,
        "status": "ok" if not limit else f"TEST RUN (limit {limit})",
        "data_revision": time.strftime("%Y-%m-%d"),
    }
    return entries, manifest
