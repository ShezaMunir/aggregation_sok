"""
scw_fetch.py -- Stage 1 retrieval for Social Choice and Welfare, 2020-2026.

Springer. Crossref carries about a third of the abstracts; the rest come from the Springer Nature Meta API
(SPRINGER_API_KEY in .env), OpenAlex and the article page.

The list of papers comes from Crossref (ISSN 1432-217X). Book reviews, editorials,
corrections and front matter are removed and counted in the manifest.

    python SCW/scw_fetch.py
    python covidence_prep.py SCW
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import run_crossref_venue  # noqa: E402

YEARS = list(range(2020, 2026 + 1))
FILTERS = {"issn": "1432-217X", "from-pub-date": "2020-01-01", "until-pub-date": "2026-12-31"}

if __name__ == "__main__":
    run_crossref_venue(HERE, "scw", "Social Choice and Welfare 2020-2026", "Social Choice and Welfare", FILTERS, YEARS,
                       springer_issn="1432-217X", use_landing=True)
