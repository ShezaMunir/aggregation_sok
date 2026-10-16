"""
cscw_fetch.py -- Stage 1 retrieval for CSCW, 2021-2026.

CSCW papers are published as issues of the Proceedings of the ACM on
Human-Computer Interaction (PACM HCI, ISSN 2573-0142), which also carries
CHI PLAY, EICS, ETRA, GROUP, ISS and MobileHCI issues. Crossref labels the
CSCW issues "CSCW1", "CSCW2" and "CSCW3" up to 2024. From 2025 PACM HCI numbers
its issues instead; each issue's editorial names its venue, which gives:

    2025: issues 2 (April) and 7 (November)
    2026: issues 2 (April) and 6 (October, the rest of the May 2025 cycle)

Recheck this table when a new issue appears. Records from the other venues'
issues are counted in the manifest note as "other venue in source".

    python CSCW/cscw_fetch.py
    python covidence_prep.py CSCW
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from pipeline_common import crossref_year, run_crossref_venue  # noqa: E402

YEARS = list(range(2021, 2027))
FILTERS = {"issn": "2573-0142", "from-pub-date": "2021-01-01", "until-pub-date": "2026-12-31"}
NUMBERED_CSCW_ISSUES = {2025: {"2", "7"}, 2026: {"2", "6"}}


def is_cscw(item):
    issue = str(item.get("issue") or "")
    if issue.upper().startswith("CSCW"):
        return True
    return issue in NUMBERED_CSCW_ISSUES.get(crossref_year(item), set())


if __name__ == "__main__":
    run_crossref_venue(HERE, "cscw", "CSCW 2021-2026", "Proceedings of the ACM on Human-Computer Interaction",
                       FILTERS, YEARS, keep=is_cscw, use_landing=False)
