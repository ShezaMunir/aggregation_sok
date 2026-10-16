"""Zotero Web API helper for the SoK reference library.

Reads ZOTERO_API_KEY and ZOTERO_USER_ID from the environment or from .env
at the repo root. Never prints the key.

    python zotero_tool.py status                 # libraries, groups, collections, recent items
    python zotero_tool.py list                   # items in the target collection
    python zotero_tool.py add ID [ID ...]        # arXiv ID/URL or DOI; --dry-run to preview
    python zotero_tool.py export-bib [PATH]      # target collection as BibTeX (default paper/refs.bib)
    python zotero_tool.py add-book --title T --year Y --publisher P [--authors|--editors 'Last, First; ...'] [--place] [--doi]
    python zotero_tool.py set-venue ARXIV_ID --venue V --year Y [--journal] [--title] [--pages] [--url] [--doi]
                                                 # convert an arXiv preprint to its published version

Target library and collection default to the SoK's NegotiationsProject group,
collection Related-Work. Override with ZOTERO_LIBRARY (e.g. groups/123 or
users/456) and ZOTERO_COLLECTION (collection name).
"""

import json
import os
import re
import sys
import uuid
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.zotero.org"
DEFAULT_LIBRARY = "groups/6667859"  # NegotiationsProject
DEFAULT_COLLECTION = "Related-Work"
ADDED_TAG = "added-by-claude"
ROOT = Path(__file__).resolve().parent


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    key = os.environ.get("ZOTERO_API_KEY")
    if not key:
        sys.exit("ZOTERO_API_KEY is not set (.env or environment).")
    return key, os.environ.get("ZOTERO_USER_ID", "").strip()


def get(key, path, **params):
    """GET one page. Returns (json, headers)."""
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Zotero-API-Key": key, "Zotero-API-Version": "3"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r), r.headers
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} on {path}: {e.read().decode()[:200]}")


def get_all(key, path, **params):
    out, start = [], 0
    while True:
        page, headers = get(key, path, start=start, limit=100, **params)
        out.extend(page)
        total = int(headers.get("Total-Results", len(out)))
        start += 100
        if start >= total or not page:
            return out


def count(key, path):
    _, headers = get(key, path, limit=1)
    return int(headers.get("Total-Results", 0))


def print_library(key, prefix, label):
    n_top = count(key, f"{prefix}/items/top")
    print(f"\n== {label}: {n_top} top-level items")

    cols = get_all(key, f"{prefix}/collections")
    by_parent = {}
    for c in cols:
        by_parent.setdefault(c["data"].get("parentCollection") or None, []).append(c)

    def walk(parent, depth):
        for c in sorted(by_parent.get(parent, []), key=lambda c: c["data"]["name"].lower()):
            print(f"   {'  ' * depth}- {c['data']['name']} ({c['meta'].get('numItems', 0)} items)")
            walk(c["key"], depth + 1)

    if cols:
        print("   Collections:")
        walk(None, 0)
    else:
        print("   Collections: none")

    recent, _ = get(key, f"{prefix}/items/top", sort="dateModified", direction="desc", limit=5)
    if recent:
        print("   Recently modified:")
        for it in recent:
            d = it["data"]
            title = (d.get("title") or "(untitled)")[:80]
            print(f"     {d.get('dateModified', '')[:10]}  {title}")


def status():
    key, user_id = load_env()
    info, _ = get(key, f"/keys/current")
    uid = str(info.get("userID", user_id))
    if user_id and user_id != uid:
        print(f"Note: ZOTERO_USER_ID in .env ({user_id}) differs from the key's user ({uid}); using the key's.")
    access = info.get("access", {})
    user_acc = access.get("user", {})
    print(f"Account: {info.get('username')} (userID {uid})")
    print(f"Key access, personal library: read={bool(user_acc.get('library'))} "
          f"write={bool(user_acc.get('write'))} files={bool(user_acc.get('files'))}")
    group_acc = access.get("groups", {})
    if group_acc:
        for gid, acc in group_acc.items():
            print(f"Key access, groups[{gid}]: read={bool(acc.get('library'))} write={bool(acc.get('write'))}")
    else:
        print("Key access, groups: none")

    if user_acc.get("library"):
        print_library(key, f"/users/{uid}", "Personal library")

    groups = get_all(key, f"/users/{uid}/groups")
    print(f"\nGroups you belong to: {len(groups)}")
    for g in groups:
        gid = g["id"]
        name = g["data"].get("name")
        readable = "all" in group_acc or str(gid) in group_acc
        if readable:
            print_library(key, f"/groups/{gid}", f"Group '{name}' (id {gid}, {g['data'].get('type')})")
        else:
            print(f"\n== Group '{name}' (id {gid}): key has no access")


# --- target collection -------------------------------------------------------

def target(key):
    lib = os.environ.get("ZOTERO_LIBRARY", DEFAULT_LIBRARY).strip("/")
    name = os.environ.get("ZOTERO_COLLECTION", DEFAULT_COLLECTION)
    cols = get_all(key, f"/{lib}/collections")
    match = [c["key"] for c in cols if c["data"]["name"] == name]
    if not match:
        sys.exit(f"No collection named '{name}' in {lib}.")
    return f"/{lib}", match[0], name


def send(key, method, path, body=None, version=None):
    headers = {"Zotero-API-Key": key, "Zotero-API-Version": "3",
               "Content-Type": "application/json"}
    if method == "POST":
        headers["Zotero-Write-Token"] = uuid.uuid4().hex
    if version is not None:
        headers["If-Unmodified-Since-Version"] = str(version)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} on {method} {path}: {e.read().decode()[:300]}")


# --- identifiers and metadata --------------------------------------------------

ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arxiv[:.]\s*)?(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.I)


def parse_id(raw):
    """Return ('arxiv', id) or ('doi', doi)."""
    doi = DOI_RE.search(raw)
    if doi:
        d = doi.group(1).rstrip(".").lower()
        m = re.fullmatch(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})(v\d+)?", d)
        return ("arxiv", m.group(1)) if m else ("doi", d)
    m = ARXIV_RE.search(raw)
    if m:
        return ("arxiv", m.group(1))
    sys.exit(f"Not an arXiv ID or DOI: {raw}")


def fetch_url(url, accept=None):
    headers = {"User-Agent": "aggregation-sok-zotero-tool/1.0"}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read()


def split_name(full):
    parts = full.strip().split()
    return {"creatorType": "author", "firstName": " ".join(parts[:-1]), "lastName": parts[-1]}


def arxiv_item(aid):
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(fetch_url(f"https://export.arxiv.org/api/query?id_list={aid}"))
    e = root.find("a:entry", ns)
    if e is None or e.find("a:title", ns) is None:
        sys.exit(f"arXiv has no record for {aid}")
    clean = lambda t: " ".join((t or "").split())
    cat = e.find("arxiv:primary_category", ns)
    cat = cat.get("term") if cat is not None else ""
    return {
        "itemType": "preprint",
        "title": clean(e.find("a:title", ns).text),
        "creators": [split_name(clean(a.find("a:name", ns).text)) for a in e.findall("a:author", ns)],
        "abstractNote": clean(e.find("a:summary", ns).text),
        "date": (e.find("a:published", ns).text or "")[:10],
        "DOI": f"10.48550/arXiv.{aid}",
        "url": f"http://arxiv.org/abs/{aid}",
        "archiveID": f"arXiv:{aid}",
        "repository": "arXiv",
        "extra": f"arXiv:{aid}" + (f" [{cat}]" if cat else ""),
    }


CROSSREF_TYPES = {
    "journal-article": ("journalArticle", "publicationTitle"),
    "proceedings-article": ("conferencePaper", "proceedingsTitle"),
    "book-chapter": ("bookSection", "bookTitle"),
}


def doi_item(doi):
    try:
        msg = json.loads(fetch_url(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"))["message"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Crossref has no record for {doi} (HTTP {e.code})")
    itype, venue_field = CROSSREF_TYPES.get(msg.get("type"), ("journalArticle", "publicationTitle"))
    parts = (msg.get("published") or msg.get("issued") or {}).get("date-parts", [[]])[0]
    item = {
        "itemType": itype,
        "title": " ".join((msg.get("title") or [""])[0].split()),
        "creators": [{"creatorType": "author", "firstName": a.get("given", ""),
                      "lastName": a.get("family", a.get("name", ""))}
                     for a in msg.get("author", [])],
        "abstractNote": re.sub(r"<[^>]+>", "", msg.get("abstract", "")).strip(),
        "date": "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts)),
        "DOI": doi,
        "url": msg.get("URL", f"https://doi.org/{doi}"),
        venue_field: (msg.get("container-title") or [""])[0],
        "pages": msg.get("page", ""),
    }
    if itype == "journalArticle":
        item.update(volume=msg.get("volume", ""), issue=msg.get("issue", ""))
    if itype == "conferencePaper":
        item["publisher"] = msg.get("publisher", "")
    return item


def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def identity(data):
    """Keys that identify a paper: DOI, arXiv ID, normalised title."""
    ids = set()
    if data.get("DOI"):
        ids.add(("doi", data["DOI"].lower()))
    for field in ("archiveID", "url", "extra", "DOI"):
        m = ARXIV_RE.search(data.get(field) or "")
        if m and ("arxiv" in (data.get(field) or "").lower()):
            ids.add(("arxiv", m.group(1)))
    if data.get("title"):
        ids.add(("title", norm_title(data["title"])))
    return ids


# --- commands ----------------------------------------------------------------

def list_items():
    key, _ = load_env()
    lib, ckey, name = target(key)
    items = get_all(key, f"{lib}/collections/{ckey}/items/top", sort="title")
    print(f"{name} ({lib}): {len(items)} items")
    for it in items:
        d = it["data"]
        first = (d.get("creators") or [{}])[0].get("lastName", "?")
        print(f"  {d.get('date', '')[:4]}  {first:<14} {d.get('title', '')[:90]}")


def library_index(key, lib):
    index = {}
    for it in get_all(key, f"{lib}/items/top"):
        for i in identity(it["data"]):
            index[i] = it
    return index


def file_or_create(key, lib, ckey, name, item, index, dry_run):
    """Add item to the collection unless the library already has it."""
    hit = next((index[i] for i in identity(item) if i in index), None)
    title = item["title"][:80]
    if hit:
        if ckey in hit["data"].get("collections", []):
            print(f"skip   already in {name}: {title}")
        elif dry_run:
            print(f"would  file existing item into {name}: {title}")
        else:
            send(key, "PATCH", f"{lib}/items/{hit['key']}",
                 {"collections": hit["data"]["collections"] + [ckey]}, version=hit["version"])
            print(f"filed  existing item into {name}: {title}")
        return
    item["collections"] = [ckey]
    item["tags"] = [{"tag": ADDED_TAG}]
    if dry_run:
        print(f"would  add to {name}: {title} ({len(item['creators'])} creators, {item['date']})")
        return
    res = send(key, "POST", f"{lib}/items", [item])
    if res.get("failed"):
        sys.exit(f"Zotero rejected {title}: {res['failed']}")
    new = res["successful"]["0"]
    for i in identity(item):
        index[i] = new
    print(f"added  to {name}: {title}")


def add(raw_ids, dry_run=False):
    key, _ = load_env()
    lib, ckey, name = target(key)
    index = library_index(key, lib)
    for raw in raw_ids:
        kind, ident = parse_id(raw)
        item = arxiv_item(ident) if kind == "arxiv" else doi_item(ident)
        file_or_create(key, lib, ckey, name, item, index, dry_run)


def people(spec, role):
    """'Last, First; Last, First' -> Zotero creators."""
    out = []
    for person in filter(None, (x.strip() for x in (spec or "").split(";"))):
        last, _, first = person.partition(",")
        out.append({"creatorType": role, "firstName": first.strip(), "lastName": last.strip()})
    return out


def add_book(a):
    key, _ = load_env()
    lib, ckey, name = target(key)
    item = {"itemType": "book", "title": a.title, "date": a.year, "publisher": a.publisher,
            "place": a.place or "", "DOI": "", "url": "",
            "creators": people(a.authors, "author") + people(a.editors, "editor")}
    if a.doi:
        item["extra"] = f"DOI: {a.doi}"
        item["url"] = f"https://doi.org/{a.doi}"
    item.pop("DOI")
    file_or_create(key, lib, ckey, name, item, library_index(key, lib), a.dry_run)


def set_venue(a):
    """Turn an arXiv preprint already in the library into its published version."""
    key, _ = load_env()
    lib = "/" + os.environ.get("ZOTERO_LIBRARY", DEFAULT_LIBRARY).strip("/")
    _, aid = parse_id(a.arxiv)
    old = next((it for it in get_all(key, f"{lib}/items/top")
                if ("arxiv", aid) in identity(it["data"])), None)
    if not old:
        sys.exit(f"No item for arXiv:{aid} in {lib}; add it first.")
    itype, venue_field = (("journalArticle", "publicationTitle") if a.journal
                          else ("conferencePaper", "proceedingsTitle"))
    tmpl, _ = get(key, "/items/new", itemType=itype)
    d = old["data"]
    new = {k: (d[k] if k in d and k != "itemType" else v) for k, v in tmpl.items()}
    for k in ("key", "version", "collections", "tags", "relations"):
        new[k] = d.get(k, new.get(k))
    new.update({"itemType": itype, venue_field: a.venue, "date": a.year,
                "extra": f"arXiv: {aid}", "DOI": a.doi or ""})
    for field, val in (("title", a.title), ("pages", a.pages), ("url", a.url),
                       ("conferenceName", a.conference)):
        if val and field in new:
            new[field] = val
    if a.dry_run:
        print(f"would  set {d['title'][:60]} -> {itype}, {a.venue} {a.year}")
        return
    send(key, "PUT", f"{lib}/items/{d['key']}", new, version=old["version"])
    print(f"set    {new['title'][:60]} -> {itype}, {a.venue} {a.year}")


# Fields Zotero exports that the paper's reference style never prints.
DROP_FIELDS = ("abstract", "keywords", "urldate", "shorttitle", "file", "annote")


def strip_fields(bib):
    """Remove DROP_FIELDS from Zotero BibTeX, matching braces so multi-line values go too."""
    out, i = [], 0
    pattern = re.compile(r"\n\s*(" + "|".join(DROP_FIELDS) + r")\s*=\s*\{", re.I)
    while True:
        m = pattern.search(bib, i)
        if not m:
            out.append(bib[i:])
            return "".join(out)
        out.append(bib[i:m.start()])
        depth, j = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(bib[j], 0)
            j += 1
        if bib[j:j + 1] == ",":
            j += 1
        i = j


# Words Zotero skips when it takes the first title word for a citation key.
KEY_SKIP = re.compile(r"\b(a|an|the|some|from|on|in|to|of|do|with)(\s+|\b)")


def default_key(entry):
    """Zotero's default citation key, author_firstword_year, built from one BibTeX entry."""
    import unicodedata
    fold = lambda t: unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    field = lambda name: (re.search(r"\n\s*" + name + r"\s*=\s*\{(.*)\},?\s*$", entry, re.M) or [None, ""])[1]
    names = field("author") or field("editor")
    last = names.split(" and ")[0].split(",")[0].replace("{", "").replace("}", "")
    last = re.sub(r"[^a-z0-9_-]", "", fold(last).lower().replace(" ", "_")) or "noauthor"
    title = fold(field("title").replace("{", "").replace("}", "")).lower()
    word = re.sub(r"[^a-z0-9_-]", "", KEY_SKIP.sub("", title).split()[0]) if title.strip() else "notitle"
    year = (re.search(r"\d{4}", field("year") or field("date") or "") or [""])[0]
    return f"{last}_{word}_{year}"


# Keys the paper already cited before default keys were used; kept as they are.
KEEP_KEYS = {"tessler_ai_2024": "tesslerAICanHelp2024"}


def rekey(bib):
    """Replace every entry's key with its default_key, adding a, b, ... on collisions."""
    out, seen = [], {}
    for entry in re.split(r"\n(?=@)", bib.strip()):
        m = re.match(r"(@\w+\{)([^,]+),", entry)
        if not m:
            out.append(entry)
            continue
        k = default_key(entry)
        n = seen.get(k, 0)
        seen[k] = n + 1
        if n:
            k += "abcdefghijklmnopqrstuvwxyz"[n - 1]
        k = KEEP_KEYS.get(k, k)
        out.append(m.group(1) + k + "," + entry[m.end():])
    return "\n\n".join(out)


def export_bib(path):
    key, _ = load_env()
    lib, ckey, name = target(key)
    chunks, start = [], 0
    while True:
        url = f"{API}{lib}/collections/{ckey}/items/top?format=bibtex&limit=100&start={start}"
        req = urllib.request.Request(url, headers={"Zotero-API-Key": key, "Zotero-API-Version": "3"})
        with urllib.request.urlopen(req, timeout=60) as r:
            total = int(r.headers.get("Total-Results", 0))
            chunks.append(r.read().decode().strip())
        start += 100
        if start >= total:
            break
    out = ROOT / path
    out.write_text(rekey(strip_fields("\n\n".join(c for c in chunks if c))) + "\n")
    print(f"Wrote {total} entries from {name} to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    args = sys.argv[1:] or ["status"]
    cmd, rest = args[0], args[1:]
    if cmd == "status":
        status()
    elif cmd == "list":
        list_items()
    elif cmd == "add" and rest:
        dry = "--dry-run" in rest
        add([r for r in rest if r != "--dry-run"], dry_run=dry)
    elif cmd == "export-bib":
        export_bib(rest[0] if rest else "paper/refs.bib")
    elif cmd in ("add-book", "set-venue"):
        import argparse
        ap = argparse.ArgumentParser(prog=f"zotero_tool.py {cmd}")
        ap.add_argument("--dry-run", action="store_true")
        ap.add_argument("--title")
        ap.add_argument("--year", required=True)
        ap.add_argument("--doi")
        if cmd == "add-book":
            ap.add_argument("--authors", help="'Last, First; Last, First'")
            ap.add_argument("--editors", help="'Last, First; Last, First'")
            ap.add_argument("--publisher", required=True)
            ap.add_argument("--place")
            a = ap.parse_args(rest)
            if not a.title:
                sys.exit("--title is required")
            add_book(a)
        else:
            ap.add_argument("arxiv")
            ap.add_argument("--venue", required=True, help="proceedings or journal title")
            ap.add_argument("--journal", action="store_true", help="journal article, not conference paper")
            ap.add_argument("--conference")
            ap.add_argument("--pages")
            ap.add_argument("--url")
            set_venue(ap.parse_args(rest))
    else:
        sys.exit(__doc__)
