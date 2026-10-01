"""
screening_schema.py -- shared screening logic for every venue pipeline.

Loads screening_keywords.yaml and applies the three-tier retention rule. All
retrieval pipelines (ACL Anthology, ACM DL, AAAI OJS, PMLR, OpenReview, DBLP,
publisher exports) import from here so the schema lives in exactly one place.

Design note: fetchers do not screen. Retrieval writes raw .bib; screening is a
separate pass over that .bib. Keeping them separate means revising the schema
never requires re-downloading, which matters because the schema WILL be revised
during the Appendix B pilot for each new community.

USE IN A PIPELINE
-----------------
    from screening_schema import load

    screener = load()                       # reads screening_keywords.yaml
    result = screener.screen(text, venue="neurips")
    if result.retain:
        ...
    result.reason          -> 'tier1' | 'preservation' | 'tier2+anchor' | ''
    result.hits            -> {'tier1': [...], 'tier2': [...], 'anchors': [...]}
    result.anchor_profile  -> which profile was applied

CLI
---
    python screening_schema.py --validate          compile every pattern
    python screening_schema.py --stats             term counts per set
    python screening_schema.py --test "some text"  explain a retention decision
    python screening_schema.py --test-file abs.txt same, from a file
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
from dataclasses import dataclass, field

DEFAULT_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "screening_keywords.yaml"
)


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------

def _read_schema_file(path):
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError:
            raise SystemExit(
                "PyYAML is required to read the schema. `pip install pyyaml`, "
                "or convert the schema to JSON and point SCHEMA_PATH at it."
            )
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalise_terms(raw_terms, where):
    """Terms may be a bare pattern string or a dict with pattern and note."""
    out = {}
    for name, value in (raw_terms or {}).items():
        if isinstance(value, str):
            pattern, note = value, ""
        elif isinstance(value, dict):
            pattern, note = value.get("pattern", ""), value.get("note", "")
        else:
            raise ValueError(f"{where}.{name}: term must be a string or a mapping")
        if not pattern:
            raise ValueError(f"{where}.{name}: empty pattern")
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"{where}.{name}: invalid regex ({exc})") from exc
        out[name] = {"pattern": pattern, "note": note, "regex": compiled}
    return out


@dataclass
class ScreenResult:
    retain: bool
    reason: str
    hits: dict = field(default_factory=dict)
    anchor_profile: str = "default"

    def terms_fired(self):
        """Flat list of the terms that drove the decision, for the RIS note."""
        return self.hits.get(self.reason.split("+")[0], [])


class Screener:
    def __init__(self, schema):
        self.version = str(schema.get("version", "?"))
        self.updated = str(schema.get("updated", "?"))
        self.settings = schema.get("settings", {}) or {}

        self.sets = {}
        for name, block in (schema.get("sets") or {}).items():
            self.sets[name] = {
                "role": block.get("role", "conditional"),
                "requires_anchor": block.get(
                    "requires_anchor", block.get("role") == "conditional"
                ),
                "description": block.get("description", ""),
                "terms": _normalise_terms(block.get("terms"), f"sets.{name}"),
            }

        self.anchor_profiles = {}
        for name, block in (schema.get("anchor_profiles") or {}).items():
            self.anchor_profiles[name] = _normalise_terms(
                block.get("terms"), f"anchor_profiles.{name}"
            )
        if "default" not in self.anchor_profiles:
            raise ValueError("anchor_profiles must define a 'default' profile")

        self.venue_profiles = {
            profile: [s.lower() for s in substrings]
            for profile, substrings in (schema.get("venue_profiles") or {}).items()
        }

        self.retired = schema.get("retired", []) or []
        self.changelog = schema.get("changelog", []) or []

        self._sufficient = [n for n, s in self.sets.items() if s["role"] == "sufficient"]
        self._conditional = [n for n, s in self.sets.items() if s["role"] == "conditional"]

    # -- profile selection ---------------------------------------------------

    def profile_for(self, venue_hint=""):
        hay = (venue_hint or "").lower()
        for profile, substrings in self.venue_profiles.items():
            if any(s in hay for s in substrings):
                return profile
        return "default"

    # -- screening -----------------------------------------------------------

    @staticmethod
    def _hits(text, terms):
        return [name for name, term in terms.items() if term["regex"].search(text)]

    def screen(self, text, venue_hint=""):
        text = text or ""
        profile = self.profile_for(venue_hint)
        anchors = self.anchor_profiles.get(profile, self.anchor_profiles["default"])

        hits = {name: self._hits(text, s["terms"]) for name, s in self.sets.items()}
        hits["anchors"] = self._hits(text, anchors)

        for name in self._sufficient:
            if hits.get(name):
                return ScreenResult(True, name, hits, profile)

        if hits["anchors"]:
            for name in self._conditional:
                if hits.get(name):
                    return ScreenResult(True, f"{name}+anchor", hits, profile)

        return ScreenResult(False, "", hits, profile)

    # -- introspection -------------------------------------------------------

    def summary(self):
        lines = [f"schema version {self.version} (updated {self.updated})"]
        for name, s in self.sets.items():
            lines.append(f"  {name:14s} role={s['role']:12s} {len(s['terms']):3d} terms")
        for name, terms in self.anchor_profiles.items():
            lines.append(f"  anchors/{name:11s} {len(terms):3d} terms")
        if self.venue_profiles:
            for profile, subs in self.venue_profiles.items():
                lines.append(f"  venues -> {profile}: {', '.join(subs)}")
        if self.retired:
            lines.append(f"  retired terms logged: {len(self.retired)}")
        return "\n".join(lines)


def load(path=None):
    return Screener(_read_schema_file(path or DEFAULT_SCHEMA_PATH))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _explain(screener, text, venue):
    result = screener.screen(text, venue)
    print(f"anchor profile : {result.anchor_profile}")
    print(f"retain         : {result.retain}")
    print(f"reason         : {result.reason or '(no match)'}")
    for key in list(screener.sets) + ["anchors"]:
        fired = result.hits.get(key) or []
        if fired:
            print(f"  {key:14s} {', '.join(fired)}")
    return 0 if result.retain else 1


def main():
    parser = argparse.ArgumentParser(description="SoK screening schema tool")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--venue", default="", help="venue hint for anchor profile")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--test", metavar="TEXT")
    parser.add_argument("--test-file", metavar="PATH")
    args = parser.parse_args()

    try:
        screener = load(args.schema)
    except (ValueError, SystemExit) as exc:
        print(f"SCHEMA ERROR: {exc}")
        return 2

    if args.validate:
        print("OK: every pattern compiles.")
        print(screener.summary())
        return 0

    if args.stats:
        print(screener.summary())
        print("\nterms by set:")
        for name, s in screener.sets.items():
            print(f"\n[{name}]")
            for term, meta in s["terms"].items():
                flag = "  *" if meta["note"] else "   "
                print(f"{flag} {term}")
        if screener.retired:
            print("\n[retired]")
            for entry in screener.retired:
                print(f"    {entry.get('term')} ({entry.get('action')}, "
                      f"{entry.get('records_matched', '?')} hits in "
                      f"{entry.get('venue_piloted', '?')})")
        return 0

    if args.test or args.test_file:
        text = args.test
        if args.test_file:
            with open(args.test_file, "r", encoding="utf-8") as f:
                text = f.read()
        return _explain(screener, text, args.venue)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
