"""
aies_fetch.py -- Stage 1 retrieval for AIES (AAAI/ACM Conference on AI, Ethics,
and Society), 2021-2026.

AIES moved publishers: 2021-2023 are ACM proceedings, read from Crossref by
each year's proceedings DOI; 2024 on are on AAAI's Open Journal Systems site,
harvested over OAI-PMH. Student abstracts (AIES:STU, AIES:A2x-SA sections) are
kept and their section is recorded; front matter is removed.

    python AIES/aies_fetch.py
    python covidence_prep.py AIES
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import run_crossref_venue, run_oai_venue  # noqa: E402

ACM_PROCEEDINGS = {2021: "10.1145/3461702", 2022: "10.1145/3514094", 2023: "10.1145/3600211"}
NAME = "AAAI/ACM Conference on AI, Ethics, and Society"

if __name__ == "__main__":
    run_crossref_venue(
        HERE, "aies", "AIES 2021-2023 (ACM)", NAME,
        {"prefix": "10.1145", "type": "proceedings-article",
         "from-pub-date": "2021-01-01", "until-pub-date": "2023-12-31"},
        sorted(ACM_PROCEEDINGS), entry_type="inproceedings",
        query={"query.container-title": "AAAI/ACM Conference on AI, Ethics, and Society"},
        doi_prefixes=[d + "." for d in ACM_PROCEEDINGS.values()])
    run_oai_venue(HERE, "aies", "AIES 2024-2026 (AAAI OJS)", "https://ojs.aaai.org/index.php/AIES/oai",
                  list(range(2024, 2027)), NAME)
