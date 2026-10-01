"""
covidence_prep.py -- Stage 2 of the SoK retrieval pipeline.

Reads the .bib files a venue's fetcher wrote to <VENUE>/bib_raw/, applies the
three-tier keyword schema plus the standalone disagreement-preservation query,
deduplicates, and writes RIS files for Covidence import. One script for every
venue; outputs and logs go in the venue's folder.

Design decisions that follow the protocol rather than convenience:

  * Deduplication happens here, not in Covidence, so the PRISMA "records
    removed before screening" figure is one you computed and can defend.
  * The preservation term set is matched WITHOUT an anchor requirement,
    because D2/D3 papers frequently describe what they do without using
    aggregation vocabulary. Precision is expected to be poor; that is accepted.
  * Every retained record logs WHICH patterns fired, so the Appendix B pilot
    (demote Tier 1 terms above 60% irrelevant, drop dead Tier 2 terms) can be
    run against real data instead of guessed at.
  * A restricted anchor list applies to NeurIPS/ICML/ICLR, where aggregation
    vocabulary appears incidentally at high rates.

Usage (from anywhere; the venue folder is resolved against the repo root):
    pip install bibtexparser pandas pyyaml
    python covidence_prep.py ACL
    python covidence_prep.py ICML
"""

import os
import re
import sys
import glob

import pandas as pd

from pipeline_common import REPO_ROOT, norm_title, parse_bib

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------

INPUT_PATTERN = "bib_raw/*.bib"       # relative to the venue folder
OUTPUT_DIR = "ris_for_covidence"      # relative to the venue folder

SCHEMA_PATH = os.path.join(REPO_ROOT, "screening_keywords.yaml")

# Design document §8.2 step 3: 20 random keyword hits per venue are hand-labelled
# to estimate precision. The seed is fixed so the sample can be regenerated.
PRECISION_SAMPLE_SIZE = 20
PRECISION_SAMPLE_SEED = 20260930

# Year window defaults to the value in the schema so it stays consistent across
# pipelines; override here only with a recorded reason.
MIN_YEAR = None           # None -> take from schema settings
MAX_YEAR = None

WRITE_COMBINED_RIS = True
RIS_CHUNK_SIZE = 2000    # Covidence handles large files, but chunks fail more gracefully


# ----------------------------------------------------------------------------
# KEYWORD SCHEMA -- shared across every venue pipeline
# ----------------------------------------------------------------------------
# Terms live in screening_keywords.yaml and are loaded through screening_schema.
# Nothing venue-specific is defined here: adding EMNLP, AAMAS, NeurIPS or a
# publisher export means pointing this script at different .bib files, not
# editing keywords. Anchor-profile selection (restricted anchors for the large
# ML venues) is handled by the schema's venue_profiles mapping.

from screening_schema import load as load_schema

SCREENER = load_schema(SCHEMA_PATH)

# ----------------------------------------------------------------------------
# LOADING AND DEDUPLICATION
# ----------------------------------------------------------------------------

def load_bibs(pattern):
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"No .bib files matched {pattern!r}. Run the venue's fetcher first.")
    rows = []
    for path in files:
        entries = parse_bib(path)
        for entry in entries:
            entry["source_file"] = os.path.basename(path)
            rows.append(entry)
        print(f"  loaded {len(entries):5d} from {os.path.basename(path)}")
    return pd.DataFrame(rows)


def deduplicate(df):
    n0 = len(df)
    df = df.copy()
    df["_doi"] = df.get("doi", pd.Series([""] * len(df))).fillna("").str.lower().str.strip()
    df["_ntitle"] = df.get("title", pd.Series([""] * len(df))).fillna("").map(norm_title)

    has_doi = df["_doi"] != ""
    dupe_doi = has_doi & df.duplicated(subset=["_doi"], keep="first")
    df = df[~dupe_doi]
    n_doi = int(dupe_doi.sum())

    dupe_title = (df["_ntitle"] != "") & df.duplicated(subset=["_ntitle"], keep="first")
    df = df[~dupe_title]
    n_title = int(dupe_title.sum())

    print(f"  duplicates removed: {n_doi} by DOI, {n_title} by normalised title "
          f"({n0} -> {len(df)})")
    return df, n_doi + n_title


# ----------------------------------------------------------------------------
# KEYWORD FILTER
# ----------------------------------------------------------------------------

def hits(text, patterns):
    return [name for name, rx in patterns.items() if rx.search(text)]


def venue_hint(row):
    """Text the schema matches against to pick an anchor profile."""
    return " ".join(str(row.get(f, "")) for f in
                    ("source_file", "venuekey", "booktitle", "journal", "series"))


def screen(df):
    for col in ("title", "abstract", "keywords"):
        if col not in df.columns:
            df[col] = ""
    df = df.copy()

    fields = SCREENER.settings.get("search_fields", ["title", "abstract", "keywords"])
    df["search_text"] = ""
    for col in fields:
        if col in df.columns:
            df["search_text"] = df["search_text"] + " " + df[col].fillna("")
    df["search_text"] = df["search_text"].astype(str).str.strip()
    df["has_abstract"] = df["abstract"].fillna("").str.strip().ne("")

    records = []
    for _, row in df.iterrows():
        result = SCREENER.screen(row["search_text"], venue_hint(row))
        records.append({
            "retain": result.retain,
            "retain_reason": result.reason,
            "anchor_profile": result.anchor_profile,
            "terms_fired": "; ".join(result.terms_fired()),
            **{f"{k}_hits": "; ".join(v) for k, v in result.hits.items()},
        })

    return pd.concat([df.reset_index(drop=True), pd.DataFrame(records)], axis=1)


# ----------------------------------------------------------------------------
# RIS OUTPUT
# ----------------------------------------------------------------------------

TYPE_MAP = {"article": "JOUR", "inproceedings": "CONF", "conference": "CONF",
            "incollection": "CHAP", "book": "BOOK", "phdthesis": "THES", "misc": "GEN"}


def clean_ris(value):
    text = str(value) if value is not None else ""
    if text.lower() == "nan":
        return ""
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def write_ris(df, path):
    with open(path, "w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            f.write(f'TY  - {TYPE_MAP.get(str(row.get("ENTRYTYPE", "misc")).lower(), "GEN")}\n')

            title = clean_ris(row.get("title"))
            if title:
                f.write(f"TI  - {title}\n")

            for author in clean_ris(row.get("author")).split(" and "):
                if author.strip():
                    f.write(f"AU  - {author.strip()}\n")

            year = clean_ris(row.get("year"))
            if year:
                f.write(f"PY  - {year}\n")

            venue = clean_ris(row.get("booktitle") or row.get("journal") or row.get("series"))
            if venue:
                f.write(f"T2  - {venue}\n")

            abstract = clean_ris(row.get("abstract"))
            if abstract:
                f.write(f"AB  - {abstract}\n")

            for tag, field in (("DO", "doi"), ("UR", "url")):
                val = clean_ris(row.get(field))
                if val:
                    f.write(f"{tag}  - {val}\n")

            for keyword in clean_ris(row.get("keywords")).split(","):
                if keyword.strip():
                    f.write(f"KW  - {keyword.strip()}\n")

            # Provenance. Covidence does not reliably preserve custom fields, but
            # N1 notes usually survive and let you trace a record back to its
            # source file and the terms that retained it.
            note = (f"source={clean_ris(row.get('source_file'))}; "
                    f"retained_by={clean_ris(row.get('retain_reason'))}; "
                    f"terms={clean_ris(row.get('terms_fired'))}; "
                    f"schema=v{SCREENER.version}")
            if not abstract:
                note += "; no abstract, screened on title"  # design document §9.1
            f.write(f"N1  - {note}\n")

            key = clean_ris(row.get("ID") or row.get("aclid"))
            if key:
                f.write(f"AN  - {key}\n")

            f.write("ER  - \n\n")


def write_chunked(df, prefix):
    paths = []
    if len(df) <= RIS_CHUNK_SIZE:
        path = f"{prefix}.ris"
        write_ris(df, path)
        return [path]
    for i in range(0, len(df), RIS_CHUNK_SIZE):
        path = f"{prefix}_part{i // RIS_CHUNK_SIZE + 1}.ris"
        write_ris(df.iloc[i:i + RIS_CHUNK_SIZE], path)
        paths.append(path)
    return paths


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------

def selection_counts(df, kept):
    """R, H and H/R per venue-year and for the venue (design document §8.2)."""
    rows = []
    groups = list(df.groupby("source_file")) + [("ALL", df)]
    for source, group in groups:
        h = int(group["retain"].sum())
        rows.append({
            "source": source.replace(".bib", ""),
            "R_records_in_window": len(group),
            "H_keyword_hits": h,
            "hit_rate": round(h / max(len(group), 1), 4),
            "abstract_coverage": round(float(group["has_abstract"].mean()), 4) if len(group) else 0.0,
        })
    return pd.DataFrame(rows)


def precision_sample(kept):
    """20 random keyword hits for hand-labelling against PICOC (§8.2 step 3)."""
    n = min(PRECISION_SAMPLE_SIZE, len(kept))
    sample = kept.sample(n=n, random_state=PRECISION_SAMPLE_SEED) if n else kept
    cols = [c for c in ["ID", "title", "year", "source_file", "retain_reason",
                        "terms_fired", "url", "abstract"] if c in sample.columns]
    sample = sample[cols].copy()
    sample["relevant"] = ""
    sample["reviewer"] = ""
    sample["notes"] = ""
    return sample


def main(venue):
    venue_dir = venue if os.path.isabs(venue) else os.path.join(REPO_ROOT, venue)
    if not os.path.isdir(venue_dir):
        raise SystemExit(f"No venue folder {venue_dir}")
    out_dir = os.path.join(venue_dir, OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)

    def log_path(name):
        return os.path.join(venue_dir, name)

    print(f"Venue folder: {os.path.relpath(venue_dir)}")
    print(f"Screening schema v{SCREENER.version} (updated {SCREENER.updated})")
    print(SCREENER.summary())
    print()
    print("Loading BibTeX...")
    df = load_bibs(os.path.join(venue_dir, INPUT_PATTERN))
    n_identified = len(df)

    print("\nDeduplicating...")
    df, n_dupes = deduplicate(df)

    lo = MIN_YEAR if MIN_YEAR is not None else SCREENER.settings.get("min_year", 2018)
    hi = MAX_YEAR if MAX_YEAR is not None else SCREENER.settings.get("max_year", 2026)
    print(f"\nApplying year window {lo}-{hi} (from schema)...")
    df["_year"] = pd.to_numeric(df.get("year"), errors="coerce")
    in_window = df["_year"].between(lo, hi)
    n_out_of_window = int((~in_window).sum())
    df = df[in_window]
    print(f"  removed {n_out_of_window} outside {lo}-{hi} "
          f"(includes records with unparseable years)")

    print("\nScreening...")
    df = screen(df)
    kept = df[df["retain"]].copy()
    rejected = df[~df["retain"]].copy()

    coverage = df["has_abstract"].mean() if len(df) else 0.0
    print(f"  abstract coverage: {coverage:.1%}")
    if coverage < 0.9:
        print("  WARNING: low abstract coverage means the tier2+anchor rule is "
              "effectively title-only for some records. Flag this in PRISMA notes.")

    print(f"\n  retained {len(kept)} / {len(df)} ({len(kept)/max(len(df),1):.1%})")
    for reason, n in kept["retain_reason"].value_counts().items():
        print(f"    by {reason:16s} {n}")

    # RIS output, one file per source plus an optional combined file
    print("\nWriting RIS...")
    for old in glob.glob(os.path.join(out_dir, "screen_*.ris")):
        os.remove(old)  # stale chunks from an earlier run would be imported twice
    for source, group in kept.groupby("source_file"):
        prefix = os.path.join(out_dir, f"screen_{source.replace('.bib','')}")
        for path in write_chunked(group, prefix):
            print(f"  {os.path.relpath(path)}  ({len(group)} records)")
    if WRITE_COMBINED_RIS and len(kept):
        for path in write_chunked(kept, os.path.join(out_dir, "screen_ALL")):
            print(f"  {os.path.relpath(path)}")

    # Logs
    keep_cols = (["ID", "title", "year", "source_file", "retain_reason",
                  "anchor_profile", "terms_fired"]
                 + [f"{n}_hits" for n in SCREENER.sets] + ["anchors_hits",
                    "has_abstract", "doi"])
    keep_cols = [c for c in keep_cols if c in kept.columns]
    kept[keep_cols].to_csv(log_path("included_manifest.csv"), index=False)
    rejected[[c for c in ["ID", "title", "year", "source_file", "has_abstract"]
              if c in rejected.columns]].to_csv(log_path("rejected_log.csv"), index=False)

    # Per-term hit counts, for the Appendix B pilot: demote Tier 1 terms with
    # poor precision, drop Tier 2 terms that never co-occur with a relevant record.
    term_rows = []
    hit_cols = [(name, f"{name}_hits") for name in list(SCREENER.sets)] + [("anchors", "anchors_hits")]
    for tier, col in hit_cols:
        if col not in df.columns:
            continue
        counts = {}
        for cell in df[col].fillna(""):
            for term in [t.strip() for t in cell.split(";") if t.strip()]:
                counts[term] = counts.get(term, 0) + 1
        for term, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            term_rows.append({"tier": tier, "term": term, "records_matched": n})
    pd.DataFrame(term_rows).to_csv(log_path("keyword_hit_report.csv"), index=False)

    # Venue selection inputs (§8.2): R, H and a precision sample to label
    selection_counts(df, kept).to_csv(log_path("selection_counts.csv"), index=False)
    precision_sample(kept).to_csv(log_path("precision_sample.csv"), index=False)

    # PRISMA
    prisma = pd.DataFrame([
        {"stage": "Records identified", "n": n_identified},
        {"stage": "Duplicates removed", "n": n_dupes},
        {"stage": "Removed outside year window", "n": n_out_of_window},
        {"stage": "Records screened by keyword", "n": len(df)},
        {"stage": "Retained for title/abstract screening", "n": len(kept)},
        {"stage": "Excluded at keyword stage", "n": len(rejected)},
    ])
    prisma.to_csv(log_path("prisma_counts.csv"), index=False)

    print(f"\nLogs in {os.path.relpath(venue_dir)}/: included_manifest.csv, rejected_log.csv, "
          "keyword_hit_report.csv, selection_counts.csv, precision_sample.csv, prisma_counts.csv")
    print(f"Import the files in {os.path.relpath(out_dir)}/ to Covidence.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python covidence_prep.py <VENUE_FOLDER>   e.g. ICML")
    main(sys.argv[1])
