"""
eaamo_fetch.py -- Stage 1 retrieval for EAAMO (ACM Conference on Equity and
Access in Algorithms, Mechanisms, and Optimization), 2021-2026, from Crossref.
Each year's proceedings has its own ACM DOI; a paper's DOI starts with it.

    python EAAMO/eaamo_fetch.py
    python covidence_prep.py EAAMO
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import run_crossref_venue  # noqa: E402

PROCEEDINGS = {2021: "10.1145/3465416", 2022: "10.1145/3551624", 2023: "10.1145/3617694",
               2024: "10.1145/3689904", 2025: "10.1145/3757887"}  # add 2026 when published

if __name__ == "__main__":
    years = sorted(PROCEEDINGS)
    run_crossref_venue(
        HERE, "eaamo", f"EAAMO {years[0]}-{years[-1]}",
        "ACM Conference on Equity and Access in Algorithms, Mechanisms, and Optimization",
        {"prefix": "10.1145", "type": "proceedings-article",
         "from-pub-date": f"{years[0]}-01-01", "until-pub-date": f"{years[-1]}-12-31"},
        years, entry_type="inproceedings",
        query={"query.container-title": "Equity and Access in Algorithms, Mechanisms, and Optimization"},
        doi_prefixes=[d + "." for d in PROCEEDINGS.values()])
