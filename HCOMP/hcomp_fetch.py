"""
hcomp_fetch.py -- Stage 1 retrieval for HCOMP (AAAI Conference on Human
Computation and Crowdsourcing), 2021-2026, harvested over OAI-PMH from AAAI's
Open Journal Systems site. Each record's volume line gives its year.

    python HCOMP/hcomp_fetch.py
    python covidence_prep.py HCOMP
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import run_oai_venue  # noqa: E402

if __name__ == "__main__":
    run_oai_venue(HERE, "hcomp", "HCOMP 2021-2026", "https://ojs.aaai.org/index.php/HCOMP/oai",
                  list(range(2021, 2027)),
                  "Proceedings of the AAAI Conference on Human Computation and Crowdsourcing")
