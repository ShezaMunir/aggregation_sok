"""
ec_fetch.py -- Stage 1 retrieval for ACM EC (Conference on Economics and
Computation), 2021-2026, from Crossref. Each year's proceedings has its own
ACM DOI; a paper's DOI starts with it. Some EC papers appear in the proceedings
as abstracts only; they are kept, and their full version is coded at full text
(design document 13).

    python EC/ec_fetch.py
    python covidence_prep.py EC
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import run_crossref_venue  # noqa: E402

# Proceedings DOI per year, read from Crossref container titles
# ("Proceedings of the 22nd ACM Conference on Economics and Computation", ...).
PROCEEDINGS = {2021: "10.1145/3465456", 2022: "10.1145/3490486", 2023: "10.1145/3580507",
               2024: "10.1145/3670865", 2025: "10.1145/3736252"}  # add 2026 when published

if __name__ == "__main__":
    years = sorted(PROCEEDINGS)
    run_crossref_venue(
        HERE, "ec", f"ACM EC {years[0]}-{years[-1]}", "ACM Conference on Economics and Computation",
        {"prefix": "10.1145", "type": "proceedings-article",
         "from-pub-date": f"{years[0]}-01-01", "until-pub-date": f"{years[-1]}-12-31"},
        years, entry_type="inproceedings",
        query={"query.container-title": "ACM Conference on Economics and Computation"},
        doi_prefixes=[d + "." for d in PROCEEDINGS.values()])
