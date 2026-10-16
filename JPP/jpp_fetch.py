"""
jpp_fetch.py -- Stage 1 retrieval for Journal of Political Philosophy, 2020-2026.

Wiley. Crossref carries no abstracts and many articles have none; OpenAlex and the article page fill what
they can, and the rest are screened on title and flagged (design document 9.1).

The list of papers comes from Crossref (ISSN 1467-9760). Book reviews, editorials,
corrections and front matter are removed and counted in the manifest.

    python JPP/jpp_fetch.py
    python covidence_prep.py JPP
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import run_crossref_venue  # noqa: E402

YEARS = list(range(2020, 2026 + 1))
FILTERS = {"issn": "1467-9760", "from-pub-date": "2020-01-01", "until-pub-date": "2026-12-31"}

if __name__ == "__main__":
    run_crossref_venue(HERE, "jpp", "Journal of Political Philosophy 2020-2026", "Journal of Political Philosophy", FILTERS, YEARS,
                       use_landing=True)
