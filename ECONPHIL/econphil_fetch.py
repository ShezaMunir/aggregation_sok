"""
econphil_fetch.py -- Stage 1 retrieval for Economics and Philosophy, 2020-2026.

Cambridge University Press. Crossref carries about two thirds of the abstracts; the rest come from OpenAlex and the Cambridge Core page.

The list of papers comes from Crossref (ISSN 1474-0028). Book reviews, editorials,
corrections and front matter are removed and counted in the manifest.

    python ECONPHIL/econphil_fetch.py
    python covidence_prep.py ECONPHIL
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import run_crossref_venue  # noqa: E402

YEARS = list(range(2020, 2026 + 1))
FILTERS = {"issn": "1474-0028", "from-pub-date": "2020-01-01", "until-pub-date": "2026-12-31"}

if __name__ == "__main__":
    run_crossref_venue(HERE, "econphil", "Economics and Philosophy 2020-2026", "Economics and Philosophy", FILTERS, YEARS,
                       use_landing=True)
