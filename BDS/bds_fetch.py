"""
bds_fetch.py -- Stage 1 retrieval for Big Data & Society, 2020-2026.

SAGE, open access. Crossref carries most abstracts; the rest come from OpenAlex and the article page.

The list of papers comes from Crossref (ISSN 2053-9517). Book reviews, editorials,
corrections and front matter are removed and counted in the manifest.

    python BDS/bds_fetch.py
    python covidence_prep.py BDS
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import run_crossref_venue  # noqa: E402

YEARS = list(range(2020, 2026 + 1))
FILTERS = {"issn": "2053-9517", "from-pub-date": "2020-01-01", "until-pub-date": "2026-12-31"}

if __name__ == "__main__":
    run_crossref_venue(HERE, "bds", "Big Data & Society 2020-2026", "Big Data & Society", FILTERS, YEARS,
                       use_landing=True)
