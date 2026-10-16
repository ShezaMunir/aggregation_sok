"""
jair_fetch.py -- Stage 1 retrieval for the Journal of Artificial Intelligence
Research, 2020-2026, harvested over OAI-PMH from jair.org (Open Journal
Systems). Crossref returns no JAIR records by ISSN, so OAI-PMH is the source.
Each record's volume line gives its year.

    python JAIR/jair_fetch.py
    python covidence_prep.py JAIR
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import run_oai_venue  # noqa: E402

if __name__ == "__main__":
    run_oai_venue(HERE, "jair", "JAIR 2020-2026", "https://www.jair.org/index.php/jair/oai",
                  list(range(2020, 2027)), "Journal of Artificial Intelligence Research",
                  entry_type="article")
