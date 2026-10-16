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
import urllib.parse
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


# ----------------------------------------------------------------------------
# Crossref-listed venues (journals, ACM proceedings, PACM HCI issues)
# ----------------------------------------------------------------------------
# Crossref gives the authoritative list of a venue's papers and the counts for
# PRISMA. Abstracts come from Crossref where the publisher deposits them, and
# otherwise, by DOI, from the Springer Nature Meta API (Springer journals),
# OpenAlex, Semantic Scholar, and the publisher's article page, in that order. Items that are not
# research papers (book reviews, editorials, corrections) are removed and
# counted. Records still without an abstract are kept and screened on title.

CROSSREF_API = "https://api.crossref.org/works"
CROSSREF_MAILTO = "aggregation-sok-retrieval@users.noreply.github.com"
OPENALEX_API = "https://api.openalex.org/works"
SPRINGER_META_API = "https://api.springernature.com/meta/v2/json"

NON_RESEARCH_PATTERNS = [
    ("book review", r"^\s*(book reviews?|review of|reviews?:|review essay|critical notice)\b"),
    ("editorial", r"^\s*(editorial|editor'?s? (note|introduction)|from the editors?|guest editorial|preface)\b"
                  r"|^\s*pacm\w*\b[^:]*\beditorial\b"),
    ("introduction to issue", r"^\s*introduction\s*(to|:)?\s*(the\s+)?(special|symposium|topical|virtual)\b"
                              r"|^\s*(special|symposium|topical) (issue|collection)\b"),
    ("correction", r"^\s*(correction|corrigendum|erratum|errata|retraction|retracted|addendum)\b"
                   r"|^\s*(correction|erratum) to\b|^\s*publisher correction\b"),
    ("front or back matter", r"\bcover and (front|back) matter\b|\b(front|back) matter\b\s*$|"
                             r"^\s*(front matter|back matter|issue information|contents|index|"
                             r"list of reviewers|acknowledg(e)?ments? to reviewers|announcements?|call for papers|"
                             r"in memoriam|obituary)\b"),
]
# A Cambridge or Wiley book review is often titled by the book itself, e.g.
# "Jane Doe, Some Book (Oxford University Press, 2021), 240 pp." Catch that shape.
BOOK_CITATION_RE = re.compile(r"(university press|press,|publishing|\bpp\.|\bisbn\b|\(\s*[A-Z][^()]*,\s*(19|20)\d\d\s*\))", re.I)
SPRINGER_NON_RESEARCH_GENRES = {
    "bookreview": "book review", "book review": "book review",
    "editorial": "editorial", "editorialnotes": "editorial", "editorial notes": "editorial",
    "correction": "correction", "erratum": "correction", "retraction": "correction",
    "announcement": "front or back matter",
}


def strip_jats(text):
    """Crossref abstracts arrive as JATS XML; keep the prose."""
    if not text:
        return ""
    text = re.sub(r"<jats:title>\s*(abstract|summary)\s*</jats:title>", " ", str(text), flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def crossref_iter(filters, select=None, rows=1000, query=None):
    """Every Crossref work matching filters (a dict), with cursor paging.

    query: optional dict of Crossref query fields, e.g.
    {"query.container-title": "..."}; results then come in relevance order.
    """
    params = {"filter": ",".join(f"{k}:{v}" for k, v in filters.items()),
              "rows": rows, "cursor": "*", "mailto": CROSSREF_MAILTO, **(query or {})}
    if select:
        params["select"] = ",".join(select)
    while True:
        url = CROSSREF_API + "?" + urllib.parse.urlencode(params)
        message = http_get_json(url)["message"]
        items = message.get("items", [])
        yield from items
        if not items or not message.get("next-cursor"):
            return
        params["cursor"] = message["next-cursor"]
        time.sleep(0.2)


def crossref_ranked(filters, query, rows=1000, max_offset=9000):
    """Crossref results in relevance order, by offset (cursor paging drops the ranking)."""
    for offset in range(0, max_offset + 1, rows):
        params = {"filter": ",".join(f"{k}:{v}" for k, v in filters.items()),
                  "rows": rows, "offset": offset, "mailto": CROSSREF_MAILTO, **query}
        items = http_get_json(CROSSREF_API + "?" + urllib.parse.urlencode(params))["message"].get("items", [])
        yield items
        if len(items) < rows:
            return
        time.sleep(0.2)


def crossref_year(item):
    for field in ("issued", "published-print", "published-online", "published", "created"):
        parts = (item.get(field) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def crossref_authors(item):
    names = []
    for person in item.get("author", []) or []:
        family, given = person.get("family", ""), person.get("given", "")
        if family:
            names.append(f"{family}, {given}".strip(", "))
        elif person.get("name"):
            names.append(person["name"])
    return names


def non_research_reason(title, genre="", n_authors=1, has_abstract=True):
    """Why an item is not a research paper, or '' if it looks like one."""
    if genre:
        reason = SPRINGER_NON_RESEARCH_GENRES.get(genre.lower().replace("_", " ").strip())
        if reason:
            return reason
    t = clean(title).lower()
    if not t:
        return "front or back matter"
    for reason, pattern in NON_RESEARCH_PATTERNS:
        if re.search(pattern, t, re.I):
            return reason
    if not has_abstract and BOOK_CITATION_RE.search(title or ""):
        return "book review"
    return ""


def env_value(name):
    """Read a key from the environment or the repo's .env; never printed."""
    if os.environ.get(name):
        return os.environ[name]
    path = os.path.join(REPO_ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    return ""


def springer_abstracts(issn, date_from, min_interval=0.7):
    """{doi: (abstract, genre)} for one Springer journal, via the Meta API.

    The basic plan allows an ISSN query with a date filter, 10 records a page,
    100 requests a minute and 500 a day.
    """
    key = env_value("SPRINGER_API_KEY")
    if not key:
        print("      no SPRINGER_API_KEY; skipping Springer abstracts")
        return {}
    out, start, total = {}, 1, None
    while total is None or start <= total:
        params = {"q": f"issn:{issn} onlinedatefrom:{date_from}", "p": 10, "s": start, "api_key": key}
        data = json.loads(http_get(SPRINGER_META_API + "?" + urllib.parse.urlencode(params)))
        total = int(data["result"][0]["total"])
        for rec in data.get("records", []):
            doi = str(rec.get("doi", "")).lower()
            abstract = rec.get("abstract", "")
            if isinstance(abstract, dict):
                abstract = " ".join(str(v) for v in abstract.values())
            genre = rec.get("genre", "")
            genre = genre[0] if isinstance(genre, list) and genre else genre
            if doi:
                out[doi] = (strip_jats(abstract), str(genre or ""))
        start += 10
        time.sleep(min_interval)
    return out


# Some OpenAlex and Semantic Scholar abstracts for ACM papers run on into the
# ACM Digital Library page ("...Total Citations0Total Downloads56... Get
# Citation Alerts"). Cut the text where that page furniture starts.
PAGE_CHROME_RE = re.compile(
    r"\s*(Total Citations\s*\d|Total Downloads\s*\d|Get Citation Alerts|New Citation Alert|"
    r"Manage my Alerts|Save to Binder|Please log in to your account|To manage your alert preferences)")


def trim_page_chrome(text):
    match = PAGE_CHROME_RE.search(text or "")
    return (text[:match.start()] if match else text or "").strip()


def openalex_abstracts(dois, batch=50):
    """{doi: abstract} rebuilt from OpenAlex's inverted index."""
    out = {}
    dois = [d for d in dois if d]
    for i in range(0, len(dois), batch):
        chunk = dois[i:i + batch]
        params = {"filter": "doi:" + "|".join(chunk), "per-page": batch,
                  "select": "doi,abstract_inverted_index", "mailto": CROSSREF_MAILTO}
        data = http_get_json(OPENALEX_API + "?" + urllib.parse.urlencode(params))
        for work in data.get("results", []):
            index = work.get("abstract_inverted_index") or {}
            if not index:
                continue
            words = sorted((pos, word) for word, positions in index.items() for pos in positions)
            doi = str(work.get("doi", "")).lower().replace("https://doi.org/", "")
            out[doi] = trim_page_chrome(" ".join(w for _, w in words))
        time.sleep(0.2)
    return out


def semanticscholar_abstracts(dois, batch=400):
    """{doi: abstract} from the Semantic Scholar batch API, with backoff on 429."""
    out = {}
    dois = [d for d in dois if d]
    for i in range(0, len(dois), batch):
        chunk = dois[i:i + batch]
        body = json.dumps({"ids": [f"DOI:{d}" for d in chunk]}).encode()
        for attempt in range(6):
            request = urllib.request.Request(
                "https://api.semanticscholar.org/graph/v1/paper/batch?fields=abstract,externalIds",
                data=body, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    papers = json.loads(response.read())
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 400 and len(chunk) > 1:
                    half = len(chunk) // 2
                    out.update(semanticscholar_abstracts(chunk[:half], batch))
                    out.update(semanticscholar_abstracts(chunk[half:], batch))
                    papers = []
                    break
                if attempt == 5 or exc.code == 400:
                    print(f"      Semantic Scholar unavailable ({exc}); skipping {len(chunk)} DOIs")
                    papers = []
                    break
                time.sleep(5 * 2 ** attempt + random.random())
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 5:
                    print(f"      Semantic Scholar unavailable ({exc}); skipping {len(chunk)} DOIs")
                    papers = []
                    break
                time.sleep(5 * 2 ** attempt + random.random())
        for doi, paper in zip(chunk, papers):
            if paper and paper.get("abstract"):
                out[doi] = trim_page_chrome(clean(paper["abstract"]))
        time.sleep(1.5)
    return out


ABSTRACT_META_RE = [
    r'<meta[^>]+name="citation_abstract"[^>]+content="([^"]+)"',
    r'<meta[^>]+name="dc\.description"[^>]+content="([^"]+)"',
    r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
    r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
]


def landing_abstract(doi):
    """The abstract from a DOI's landing page meta tags, or '' if none."""
    try:
        page = http_get(f"https://doi.org/{doi}", timeout=45, retries=2)
    except Exception:
        return None
    for pattern in ABSTRACT_META_RE:
        match = re.search(pattern, page, re.I | re.S)
        if match:
            text = clean(html.unescape(match.group(1)))
            if len(text.split()) >= 30:  # site blurbs are short; abstracts are not
                return text
    return ""


def crossref_venue(venue, name, filters, years, entry_type="article",
                   keep=None, springer_issn=None, use_landing=False, min_interval=1.0,
                   query=None, doi_prefixes=None):
    """Retrieve one Crossref-listed venue. Returns {year: (entries, manifest row)}.

    filters: Crossref filter dict. keep(item) -> bool drops records outside the
    venue (e.g. other conferences' issues of PACM HCI). Abstracts are filled by
    DOI from Springer (springer_issn), OpenAlex, then the article page
    (use_landing). For proceedings, query ranks the venue's papers first and
    doi_prefixes (e.g. "10.1145/3670865.") keeps only them; the scan stops once
    a long run of results holds none of them.
    """
    lo, hi = min(years), max(years)
    items, outside, dupes, seen = [], Counter(), 0, set()
    prefixes = tuple(p.lower() for p in (doi_prefixes or []))

    def candidates():
        if not query:
            yield from crossref_iter(filters)
            return
        # Ranked search, one year at a time; stop at the first page with none of
        # the venue's DOIs once some have been found.
        for year in range(lo, hi + 1):
            yearly = {**filters, "from-pub-date": f"{year}-01-01", "until-pub-date": f"{year}-12-31"}
            found = False
            for page in crossref_ranked(yearly, query):
                hits = [i for i in page if str(i.get("DOI", "")).lower().startswith(prefixes)]
                yield from hits
                if hits:
                    found = True
                elif found:
                    break

    for item in candidates():
        doi = str(item.get("DOI", "")).lower()
        year = crossref_year(item)
        if prefixes and not doi.startswith(prefixes):
            continue
        if keep and not keep(item):
            outside["other venue in source"] += 1
            continue
        if year is None or not lo <= year <= hi:
            outside["outside window"] += 1
            continue
        if doi in seen:
            dupes += 1
            continue
        seen.add(doi)
        items.append(item)
    print(f"      Crossref: {len(items)} records {lo}-{hi}"
          + (f" ({', '.join(f'{k}: {v}' for k, v in outside.items())})" if outside else ""))

    abstracts, genres, source_of = {}, {}, {}
    for item in items:
        doi = item["DOI"].lower()
        text = strip_jats(item.get("abstract"))
        if len(text.split()) >= 30:
            abstracts[doi], source_of[doi] = text, "crossref"
    if springer_issn:
        for doi, (text, genre) in springer_abstracts(springer_issn, f"{lo - 1}-07-01").items():
            genres[doi] = genre
            if doi not in abstracts and len(text.split()) >= 30:
                abstracts[doi], source_of[doi] = text, "springer"
    missing = [i["DOI"].lower() for i in items if i["DOI"].lower() not in abstracts]
    for doi, text in openalex_abstracts(missing).items():
        if doi not in abstracts and len(text.split()) >= 30:
            abstracts[doi], source_of[doi] = text, "openalex"
    missing = [i["DOI"].lower() for i in items if i["DOI"].lower() not in abstracts]
    for doi, text in semanticscholar_abstracts(missing).items():
        if doi not in abstracts and len(text.split()) >= 30:
            abstracts[doi], source_of[doi] = text, "semantic scholar"

    by_year = {}
    for item in items:
        by_year.setdefault(crossref_year(item), []).append(item)

    results = {}
    for year in sorted(by_year):
        entries, excluded, pages, page_failures = [], Counter(), 0, 0
        for item in sorted(by_year[year], key=lambda i: i["DOI"]):
            doi = item["DOI"].lower()
            title = clean(" ".join(item.get("title") or []))
            authors = crossref_authors(item)
            if doi not in abstracts and use_landing:
                text = landing_abstract(doi)
                pages += 1
                if text is None:
                    page_failures += 1
                elif text:
                    abstracts[doi], source_of[doi] = text, "article page"
                time.sleep(min_interval)
            reason = non_research_reason(title, genres.get(doi, ""), len(authors), doi in abstracts)
            if reason:
                excluded[reason] += 1
                continue
            suffix = re.sub(r"[^A-Za-z0-9]+", "-", doi.split("/", 1)[-1]).strip("-")
            container = clean(" ".join(item.get("container-title") or [])) or name
            fields = [("title", title), ("author", " and ".join(authors)), ("year", str(year)),
                      ("journal" if entry_type == "article" else "booktitle", container),
                      ("volume", item.get("volume")), ("number", item.get("issue")),
                      ("pages", item.get("page")), ("doi", item["DOI"]),
                      ("url", f"https://doi.org/{item['DOI']}"),
                      ("abstract", abstracts.get(doi, "")),
                      ("keywords", "; ".join(item.get("subject") or [])),
                      ("abstractsource", source_of.get(doi, "")), ("venuekey", venue)]
            entries.append(bib_entry(f"{venue}{year}-{suffix}", fields, entry_type))
        n_abs = sum(1 for e in entries if "abstract = {" in e)
        sources = Counter(source_of[i["DOI"].lower()] for i in by_year[year]
                          if i["DOI"].lower() in source_of)
        results[year] = (entries, {
            "venue": venue, "year": year, "source": "Crossref",
            "listed": len(by_year[year]),
            "excluded_other_tracks": "; ".join(f"{k}: {v}" for k, v in excluded.most_common()),
            "listing_duplicates": dupes if year == lo else 0,
            "papers": len(entries), "with_abstract": n_abs,
            "abstract_coverage": round(n_abs / max(len(entries), 1), 4),
            "pages_fetched": pages, "page_failures": page_failures, "status": "ok",
            "data_revision": time.strftime("%Y-%m-%d"),
            "note": "abstracts: " + ", ".join(f"{k} {v}" for k, v in sources.most_common()),
        })
    return results


def run_crossref_venue(here, venue, label, name, filters, years, **kwargs):
    """Fetch, write one .bib per year and the manifest, as the other fetchers do."""
    out_dir = os.path.join(here, "bib_raw")
    manifest = os.path.join(here, f"{venue}_fetch_manifest.csv")
    print(f"  {label}")
    results = crossref_venue(venue, name, filters, years, **kwargs)
    for year, (entries, row) in results.items():
        path = os.path.join(out_dir, f"{venue}_{year}.bib")
        write_bib(path, entries)
        write_manifest(manifest, [row])
        print(f"      {year}: listed {row['listed']}, removed [{row['excluded_other_tracks'] or 'none'}] "
              f"-> {row['papers']} papers, {row['abstract_coverage']:.1%} with abstract ({row['note']})")
    print(f"  Manifest: {os.path.relpath(manifest)}")
    print(f"  Next: python covidence_prep.py {os.path.basename(here)}")


# ----------------------------------------------------------------------------
# OJS venues over OAI-PMH (AAAI OJS: AIES 2024 on, HCOMP; jair.org: JAIR)
# ----------------------------------------------------------------------------
# Open Journal Systems sites expose every published article over OAI-PMH as
# Dublin Core: title, creators, abstract (dc:description), DOI and a source line
# naming the volume and its year, e.g. "...; Vol. 7 (2019): ...; 135-143".

OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/",
          "dc": "http://purl.org/dc/elements/1.1/"}
VOLUME_YEAR_RE = re.compile(r"Vol\.?\s*\d+[^;()]*\((\d{4})\)")


def oai_records(base_url, metadata_prefix="oai_dc", min_interval=1.0):
    """Every record an OAI-PMH endpoint lists, as dicts of Dublin Core lists."""
    import xml.etree.ElementTree as ET
    params = {"verb": "ListRecords", "metadataPrefix": metadata_prefix}
    while True:
        root = ET.fromstring(http_get(base_url + "?" + urllib.parse.urlencode(params), timeout=120))
        for rec in root.iter(f"{{{OAI_NS['oai']}}}record"):
            header = rec.find("oai:header", OAI_NS)
            if header is not None and header.get("status") == "deleted":
                continue
            fields = {}
            for el in rec.iter():
                if el.tag.startswith(f"{{{OAI_NS['dc']}}}") and el.text:
                    fields.setdefault(el.tag.split("}")[1], []).append(el.text.strip())
            spec = rec.find("oai:header/oai:setSpec", OAI_NS)
            fields["setSpec"] = [spec.text] if spec is not None and spec.text else []
            yield fields
        token = root.find(".//oai:resumptionToken", OAI_NS)
        if token is None or not (token.text or "").strip():
            return
        params = {"verb": "ListRecords", "resumptionToken": token.text.strip()}
        time.sleep(min_interval)


def oai_year(fields):
    for source in fields.get("source", []):
        match = VOLUME_YEAR_RE.search(source)
        if match:
            return int(match.group(1))
    for date in fields.get("date", []):
        if re.match(r"\d{4}", date):
            return int(date[:4])
    return None


def run_oai_venue(here, venue, label, base_url, years, name, entry_type="inproceedings", keep=None):
    """Harvest an OJS venue, write one .bib per year and the manifest."""
    out_dir = os.path.join(here, "bib_raw")
    manifest = os.path.join(here, f"{venue}_fetch_manifest.csv")
    lo, hi = min(years), max(years)
    print(f"  {label}")
    by_year, outside = {}, Counter()
    for fields in oai_records(base_url):
        year = oai_year(fields)
        if keep and not keep(fields):
            outside["other venue in source"] += 1
            continue
        if year is None or not lo <= year <= hi:
            outside["outside window"] += 1
            continue
        by_year.setdefault(year, []).append(fields)
    print(f"      OAI-PMH: {sum(len(v) for v in by_year.values())} records {lo}-{hi} "
          f"({', '.join(f'{k}: {v}' for k, v in outside.items()) or 'none outside'})")
    for year in sorted(by_year):
        entries, excluded, seen, dupes = [], Counter(), set(), 0
        for fields in by_year[year]:
            title = clean((fields.get("title") or [""])[0])
            abstract = clean(html.unescape(re.sub(r"<[^>]+>", " ", " ".join(fields.get("description", [])))))
            doi = next((i for i in fields.get("identifier", []) if i.startswith("10.")), "")
            url = next((i for i in fields.get("identifier", []) if i.startswith("http")), "")
            ident = (doi or url or title).lower()
            if ident in seen:
                dupes += 1
                continue
            seen.add(ident)
            reason = non_research_reason(title, "", len(fields.get("creator", [])), bool(abstract))
            if any(re.search(r":(FRNT|FMT|FRONT|BACK)\b", s) for s in fields.get("setSpec", [])):
                reason = "front or back matter"
            if reason:
                excluded[reason] += 1
                continue
            suffix = re.sub(r"[^A-Za-z0-9]+", "-", (doi.split("/", 1)[-1] if doi else url.rsplit("/", 1)[-1])).strip("-")
            entries.append(bib_entry(f"{venue}{year}-{suffix}", [
                ("title", title), ("author", " and ".join(fields.get("creator", []))),
                ("year", str(year)), ("journal" if entry_type == "article" else "booktitle", name),
                ("doi", doi), ("url", url or (f"https://doi.org/{doi}" if doi else "")),
                ("abstract", abstract), ("keywords", "; ".join(fields.get("subject", []))),
                ("section", "; ".join(fields.get("setSpec", []))), ("venuekey", venue),
            ], entry_type))
        n_abs = sum(1 for e in entries if "abstract = {" in e)
        row = {"venue": venue, "year": year, "source": base_url.split("/oai")[0] + " (OAI-PMH)",
               "listed": len(by_year[year]),
               "excluded_other_tracks": "; ".join(f"{k}: {v}" for k, v in excluded.most_common()),
               "listing_duplicates": dupes, "papers": len(entries), "with_abstract": n_abs,
               "abstract_coverage": round(n_abs / max(len(entries), 1), 4),
               "pages_fetched": 0, "page_failures": 0, "status": "ok",
               "data_revision": time.strftime("%Y-%m-%d"), "note": ""}
        write_bib(os.path.join(out_dir, f"{venue}_{year}.bib"), entries)
        write_manifest(manifest, [row])
        print(f"      {year}: listed {row['listed']}, removed [{row['excluded_other_tracks'] or 'none'}] "
              f"-> {row['papers']} papers, {row['abstract_coverage']:.1%} with abstract")
    print(f"  Manifest: {os.path.relpath(manifest)}")
    print(f"  Next: python covidence_prep.py {os.path.basename(here)}")
