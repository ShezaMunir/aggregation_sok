"""
acl_fetch.py -- Stage 1 of the SoK retrieval pipeline.

Pulls ACL Anthology records for the configured venues and years and writes one
.bib per venue-year with abstracts, plus a manifest CSV recording counts and
abstract coverage per volume.

WHY THIS PARSES XML RATHER THAN USING acl-anthology-py
------------------------------------------------------
The released acl-anthology-py (0.5.1 at time of writing) cannot parse the
current Anthology data. Every collection tested raised either
    AnthologyXMLError: unsupported element for <frontmatter>
or  ValueError: Unsupported element for Volume: <pdf>
because the data schema has moved ahead of the library. This is not an edge
case; it affects 2023 through 2026 alike, and there is no newer release.

The XML under data/xml/ is simple, stable, and versioned in the same repo, so
parsing it with the standard library removes a dependency that is currently
broken and would otherwise be a single point of failure for the whole pipeline.
If the library catches up, nothing here needs to change.

SETUP
-----
    pip install pandas
    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/acl-org/acl-anthology.git anthology_repo
    cd anthology_repo && git sparse-checkout set data/xml && cd ..

That is a ~180 MB sparse checkout of the XML only, not the full repo. Re-run
`git pull` before a later retrieval round, and record the commit hash (printed
on every run) in the PRISMA notes so the search is reproducible.

    python acl_fetch.py
    python ../covidence_prep.py ACL
"""

import os
import re
import csv
import subprocess
import xml.etree.ElementTree as ET

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------

ANTHOLOGY_XML_DIR = "anthology_repo/data/xml"

YEARS = ["2025", "2026"]

# Add the rest of the Class B NLP cluster here when ready. Files are named
# "<year>.<venue>.xml", e.g. 2025.emnlp.xml, 2025.findings.xml, 2025.tacl.xml
VENUES = [
    "acl",
    # "emnlp",
    # "naacl",
    # "eacl",
    # "findings",
    # "tacl",
]

# Written next to this script, where `python covidence_prep.py ACL` looks for them.
HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(HERE, "bib_raw")
MANIFEST_PATH = os.path.join(HERE, "acl_fetch_manifest.csv")

# Main-track long papers only. Set True to also admit short papers; permitted by
# the protocol but it materially increases the screening load for this cluster.
INCLUDE_SHORT_PAPERS = False

INCLUDE_VOLUME_IDS = ["long", "main"] + (["short"] if INCLUDE_SHORT_PAPERS else [])
EXCLUDE_VOLUME_IDS = ["demo", "tutorial", "srw", "student", "industry",
                      "workshop", "shared", "invited"]


# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------

def node_text(node):
    """Titles and abstracts contain inline markup (<fixed-case>, <i>, <b>,
    <tex-math>, <url>). itertext flattens them; braces are stripped so the value
    round-trips through BibTeX."""
    if node is None:
        return ""
    text = "".join(node.itertext())
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def author_string(paper):
    names = []
    for author in paper.findall("author"):
        first = node_text(author.find("first"))
        last = node_text(author.find("last"))
        if last and first:
            names.append(f"{last}, {first}")
        elif last or first:
            names.append(last or first)
    return " and ".join(names)


def volume_wanted(volume_id):
    vid = (volume_id or "").lower()
    if any(bad in vid for bad in EXCLUDE_VOLUME_IDS):
        return False
    return any(good in vid for good in INCLUDE_VOLUME_IDS)


def repo_commit(xml_dir):
    try:
        return subprocess.check_output(
            ["git", "-C", xml_dir, "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def build_entry(paper, collection_id, volume_id, volume_title, year, venue):
    paper_id = paper.get("id")
    if not paper_id:
        return None, False

    title = node_text(paper.find("title"))
    if not title:
        return None, False  # frontmatter and malformed records

    full_id = f"{collection_id}-{volume_id}.{paper_id}"
    abstract = node_text(paper.find("abstract"))

    fields = [
        ("title", title),
        ("author", author_string(paper)),
        ("year", str(year)),
        ("booktitle", volume_title),
        ("pages", node_text(paper.find("pages"))),
        ("doi", node_text(paper.find("doi"))),
        ("url", f"https://aclanthology.org/{full_id}/"),
        ("abstract", abstract),
        # Provenance, read back in stage 2
        ("aclid", full_id),
        ("venuekey", venue),
    ]

    lines = [f"@inproceedings{{{full_id},"]
    lines += [f"  {k} = {{{v}}}," for k, v in fields if v]
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines), bool(abstract)


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------

def main():
    if not os.path.isdir(ANTHOLOGY_XML_DIR):
        raise SystemExit(
            f"{ANTHOLOGY_XML_DIR} not found. Clone the anthology repo first:\n"
            "  git clone --depth 1 --filter=blob:none --sparse "
            "https://github.com/acl-org/acl-anthology.git anthology_repo\n"
            "  cd anthology_repo && git sparse-checkout set data/xml"
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    commit = repo_commit(ANTHOLOGY_XML_DIR)
    print(f"Anthology data revision: {commit}   (record this in PRISMA notes)\n")

    manifest_rows = []
    grand_total = 0

    for venue in VENUES:
        for year in YEARS:
            collection_id = f"{year}.{venue}"
            xml_path = os.path.join(ANTHOLOGY_XML_DIR, f"{collection_id}.xml")

            if not os.path.exists(xml_path):
                print(f"  SKIP {collection_id}: no XML file "
                      f"(proceedings may not be published yet)")
                manifest_rows.append({
                    "venue": venue, "year": year, "volume": "", "volume_id": "",
                    "papers": 0, "with_abstract": 0, "abstract_coverage": "",
                    "status": "file_not_found", "data_revision": commit,
                })
                continue

            root = ET.parse(xml_path).getroot()
            entries, n_papers, n_abstract = [], 0, 0
            print(f"  {collection_id}")

            for volume in root.findall("volume"):
                volume_id = volume.get("id", "")
                if not volume_wanted(volume_id):
                    continue

                volume_title = node_text(volume.find("meta/booktitle")) or collection_id
                v_papers, v_abstract = 0, 0

                for paper in volume.findall("paper"):
                    entry, has_abstract = build_entry(
                        paper, collection_id, volume_id, volume_title, year, venue
                    )
                    if entry is None:
                        continue
                    entries.append(entry)
                    v_papers += 1
                    v_abstract += int(has_abstract)

                if v_papers:
                    coverage = v_abstract / v_papers
                    flag = "   <-- LOW ABSTRACT COVERAGE" if coverage < 0.9 else ""
                    print(f"      [{volume_id:6s}] {v_papers:5d} papers, "
                          f"{coverage:6.1%} abstracts{flag}")
                    manifest_rows.append({
                        "venue": venue, "year": year, "volume": volume_title,
                        "volume_id": volume_id, "papers": v_papers,
                        "with_abstract": v_abstract,
                        "abstract_coverage": round(coverage, 4),
                        "status": "ok", "data_revision": commit,
                    })
                    n_papers += v_papers
                    n_abstract += v_abstract

            if entries:
                out_path = os.path.join(OUTPUT_DIR, f"{venue}_{year}.bib")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write("\n\n".join(entries) + "\n")
                print(f"      -> {n_papers} papers written to {out_path}")
                grand_total += n_papers
            else:
                print(f"      -> no matching volumes")

    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "venue", "year", "volume", "volume_id", "papers",
            "with_abstract", "abstract_coverage", "status", "data_revision",
        ])
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"\nIdentification total: {grand_total} records")
    print(f"Manifest: {MANIFEST_PATH}")
    print("Next: python covidence_prep.py ACL   (from the repo root)")


if __name__ == "__main__":
    main()
