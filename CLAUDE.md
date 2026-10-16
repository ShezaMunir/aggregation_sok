# CLAUDE.md

## Secrets

- Never read, print, cat, grep, or otherwise open `.env` or any `.env.*` file except `.env.example`. It holds the Zotero API key.
- Scripts may load `.env` themselves at runtime; never echo or log its values.
- To check whether a variable is set, test for presence only (e.g. `[ -n "$ZOTERO_API_KEY" ]`), never print it.

## References

- Papers for this SoK live in the Zotero group NegotiationsProject, collection Related-Work. `zotero_tool.py` adds to it and exports `paper/refs.bib`.
- Whenever a paper is cited, relied on, or recommended in this project, add it with the `zotero-add` skill.
