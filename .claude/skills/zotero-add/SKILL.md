---
name: zotero-add
description: Add papers to the SoK's Zotero collection (NegotiationsProject group → Related-Work) and refresh refs.bib. Use whenever a paper is cited, relied on, or recommended in this project's writing — related work, background, the design doc — or when the user says to add a paper to Zotero.
---

# Add papers to Zotero

1. Collect identifiers for each paper: arXiv ID or URL, or DOI. Prefer the DOI of the
   published version (venue proceedings or journal) over arXiv when one exists, since the
   paper cites the archival version. Look it up if needed; never guess a DOI.
2. Preview: `python3 zotero_tool.py add <id> [<id> ...] --dry-run`
3. If the preview looks right, run the same command without `--dry-run`. Already-present
   papers are skipped or filed into the collection; new ones get the `added-by-claude` tag.
4. Refresh the bibliography (`paper/refs.bib`): `python3 zotero_tool.py export-bib`
5. Tell the user which papers were added, which were skipped, and the BibTeX keys for any
   new entries.

Never read `.env`; the script loads the API key itself (see CLAUDE.md).
