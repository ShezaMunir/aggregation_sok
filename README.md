
reference_code -> contains parsing and filtration code for a previous SOK. can be used for reference.

## Retrieval pipeline

    pip install bibtexparser pandas pyyaml

Stage 1, one fetcher per venue, writes raw records to `<VENUE>/bib_raw/` and a fetch manifest:

    python ACL/acl_fetch.py      # ACL Anthology XML (needs the sparse anthology clone, see the script)
    python ICML/icml_fetch.py    # PMLR 2021-2025, icml.cc 2026
    python ICLR/iclr_fetch.py    # iclr.cc 2021-2026
    python CHI/chi_fetch.py      # ACM exports 2021-2025, SIGCHI program 2026

Stage 2, shared by every venue, applies `screening_keywords.yaml` and writes RIS files for Covidence to `<VENUE>/ris_for_covidence/`, plus PRISMA counts, per-term hit counts, R/H selection counts and a precision sample to `<VENUE>/`:

    python covidence_prep.py ICML

Test a phrase against the keyword schema: `python screening_schema.py --test "your text"`.
