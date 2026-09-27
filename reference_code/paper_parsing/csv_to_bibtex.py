import pandas as pd
import re
import os

def extract_venue_from_filename(csv_path):
    base = os.path.basename(csv_path)
    venue_raw = base.split("_")[0]  # "aies", "facct", etc.
    return venue_raw.upper()        # "AIES", "FACCT"

def make_citekey(title, authors, year, venue):
    first_author = authors.split(",")[0].split()[-1]  # last name of first author
    year = str(year)
    title_key = re.sub(r'\W+', '', title.split()[0])  # first word cleaned
    return f"{first_author}{year}{venue}{title_key}"

def convert_csv_to_bibtex(csv_path, bibtex_path):
    df = pd.read_csv(csv_path)
    venue = extract_venue_from_filename(csv_path)

    bib_entries = []

    for _, row in df.iterrows():
        title = row["title"]
        authors = row["authors"]
        abstract = row.get("abstract", "")
        url = row.get("url", "")
        tags = row.get("tags", "")
        year = row.get("year", "")

        key = make_citekey(title, authors, year, venue)

        entry = (
f"@inproceedings{{{key},\n"
f"  author = {{{authors}}},\n"
f"  title = {{{title}}},\n"
f"  booktitle = {{{venue}}},\n"
f"  year = {{{year}}},\n"
f"  url = {{{url}}},\n"
f"  keywords = {{{tags}}},\n"
f"  abstract = {{{abstract}}}\n"
f"}}\n"
        )

        bib_entries.append(entry)

    with open(bibtex_path, "w", encoding="utf-8") as f:
        f.write("\n".join(bib_entries))

    print(f"BibTeX written to: {bibtex_path}")

# Example:
convert_csv_to_bibtex("facct/facct_filtered_combined.csv", "facct/facct_filtered_combined.bib")
