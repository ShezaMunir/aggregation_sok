
reference_code -> contains parsing and filtration code for a previous SOK. can be used for reference.

## Retrieval pipeline

    pip install bibtexparser pandas pyyaml pypdf

Stage 1, one fetcher per venue, writes raw records to `<VENUE>/bib_raw/` (git-ignored) and a fetch manifest `<VENUE>/<venue>_fetch_manifest.csv` recording, per year, what the source listed, what was removed and why, and abstract coverage.

Stage 2, shared by every venue, applies `screening_keywords.yaml` and writes RIS files for Covidence to `<VENUE>/ris_for_covidence/`, plus PRISMA counts, per-term hit counts, R/H selection counts and a precision sample to `<VENUE>/`:

    python covidence_prep.py ICML

Test a phrase against the keyword schema: `python screening_schema.py --test "your text"`.

### Venues

| Folder | Venue | Years | Source |
|---|---|---|---|
| `ICML` | ICML | 2021-2026 | PMLR 2021-2025, icml.cc 2026 |
| `ICLR` | ICLR | 2021-2026 | iclr.cc |
| `NEURIPS` | NeurIPS | 2025-2026 | neurips.cc; main, datasets and position-paper tracks, tagged in `included_manifest.csv` |
| `ACL` | ACL | 2025-2026 | ACL Anthology XML (needs the sparse anthology clone, see the script) |
| `CHI` | CHI | 2021-2026 | ACM exports 2021-2025, SIGCHI program 2026 |
| `CSCW` | CSCW | 2021-2026 | Crossref, CSCW issues of PACM HCI |
| `AIES` | AIES | 2021-2026 | Crossref (ACM) 2021-2023, AAAI OJS over OAI-PMH 2024 on |
| `EAAMO` | EAAMO | 2021-2025 | Crossref (ACM proceedings DOI per year) |
| `EC` | ACM EC | 2021-2025 | Crossref (ACM proceedings DOI per year) |
| `HCOMP` | HCOMP | 2021-2024 | AAAI OJS over OAI-PMH |
| `AAMAS` | AAMAS | 2021-2026 | Crossref (IFAAMAS DOI prefix 10.65109) 2021-2025; IFAAMAS table of contents 2026, tracks tagged |
| `JAIR` | JAIR | 2020-2026 | jair.org over OAI-PMH |
| `BDS` | Big Data & Society | 2020-2026 | Crossref |
| `SCW` | Social Choice and Welfare | 2020-2026 | Crossref + Springer Nature Meta API |
| `PHILTECH` | Philosophy & Technology | 2020-2026 | Crossref + Springer Nature Meta API |
| `ECONPHIL` | Economics and Philosophy | 2020-2026 | Crossref |
| `EPISTEME` | Episteme | 2020-2026 | Crossref |
| `JPP` | Journal of Political Philosophy | 2020-2023 | Crossref; the journal stopped publishing after 2023 and closed in January 2026 |

Run any of them as `python <FOLDER>/<venue>_fetch.py`, then `python covidence_prep.py <FOLDER>`. For NeurIPS and AAMAS, add the track column after screening with `python NEURIPS/neurips_fetch.py --tag-manifest` or `python AAMAS/aamas_fetch.py --tag-manifest`.

Years not yet available: HCOMP 2025-2026 (not on AAAI OJS yet), EC and EAAMO 2026 (add the proceedings DOI to the fetcher's `PROCEEDINGS` table when published). From 2025, PACM HCI numbers its issues instead of naming them; `CSCW/cscw_fetch.py` maps the numbered CSCW issues and needs the new issue numbers each year.

### Shared fetchers in `pipeline_common.py`

- **Conference sites** (`miniconf_year`): ICLR, ICML 2026 and NeurIPS accepted-paper lists, with per-paper pages fetched when the list has no abstracts.
- **Crossref** (`run_crossref_venue`): journals by ISSN, ACM proceedings by proceedings DOI (ranked search per year, since cursor paging drops the ranking), PACM HCI issues. Book reviews, editorials, corrections and front matter are removed and counted.
- **OAI-PMH** (`run_oai_venue`): Open Journal Systems sites (AAAI OJS, jair.org).

Missing abstracts are filled by DOI from the Springer Nature Meta API (Springer journals), OpenAlex, Semantic Scholar, and the article page, in that order; each record's `abstractsource` field says which. ACM and Springer article pages block scripted access, so a few records are screened on title alone and flagged.

### Keys

API keys go in `.env` at the repo root (git-ignored; see `.env.example`). The fetchers read them and never print them.

- `SPRINGER_API_KEY`: Springer Nature Meta API, basic plan (free at dev.springernature.com). Used by `SCW` and `PHILTECH`.
- `ZOTERO_API_KEY`, `ZOTERO_USER_ID`: `zotero_tool.py`, which adds papers to the group library and exports `paper/refs.bib`.

### Checks

`python make_spot_check.py` draws 5 keyword-retained records per venue into `spot_check_sample.csv`, for a reviewer to confirm against the publisher's page that each paper belongs to the venue and year and that its abstract is that paper's.
