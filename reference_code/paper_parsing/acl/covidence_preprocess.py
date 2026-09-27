import bibtexparser
from bibtexparser.bparser import BibTexParser
import pandas as pd
import re
import glob
import os

# --- CONFIGURATION ---
INPUT_FILE_PATTERN = "*.bib" 
OUTPUT_REJECTED_FILE = "comprehensive_rejected_log.csv"

# --- 1. REFINED KEYWORD TIERS (Aggregation & Labor Focused) ---

sufficient_kw = [
    # Platforms & Labor Infrastructure (MUST KEEP)
    r"mechanical turk", r"mturk", r"prolific", r"labelbox", r"appen", 
    r"scale ai", r"figshare", r"crowdwork", r"crowdsourc", r"amazon mechanical",
    
    # Specific Aggregation Models & Mechanics
    r"dawid-skene", r"\bGLAD\b", r"\bMACE\b", r"\bIAA\b", r"inter-rater reliability",
    r"truth discovery", r"latent class analysis", r"weighted (?:voting|aggregation)",
    r"expectation-maximization", r"label noise modeling", r"noisy label (?:aggregation|correction)",
    r"consensus (?:mechanism|method|protocol)", r"aggregation (?:method|model|framework)",
    
    # Modern / LLM-Based Aggregation
    r"llm-as-a-judge", r"model-as-annotator", r"generative annotation",
    r"RLHF", r"human feedback", r"preference (?:optimization|learning)", r"instruction tuning"
]

conditional_kw = [
    r"aggregation", r"consensus", r"adjudication", r"reconciliation",
    r"ambiguity", r"subjectiv", r"disagreement", r"pluralis", r"positionality",
    r"epistemic", r"wage", r"labor", r"alignment", r"ground truth analysis",
    r"bias", r"uncertainty", r"conflict resolution", r"label quality", r"soft labels?"
]

context_kw = [
    r"annotat(?:or|ion)", r"label(?:er|ing)", r"rater", r"coder", 
    r"human judge", r"worker", r"gold standard", r"reference standard",
    r"subjective (?:task|label)", r"ground truth (?:construction|generation)"
]

pattern_sufficient = re.compile("|".join(sufficient_kw), flags=re.IGNORECASE)
pattern_conditional = re.compile("|".join(conditional_kw), flags=re.IGNORECASE)
pattern_context = re.compile("|".join(context_kw), flags=re.IGNORECASE)

# --- 2. IMPROVED RIS WRITER ---

def write_df_to_ris(df, output_path):
    TYPE_MAPPING = {'article': 'JOUR', 'inproceedings': 'CONF', 'conference': 'CONF', 'misc': 'GEN'}
    with open(output_path, 'w', encoding='utf-8') as f:
        for _, row in df.iterrows():
            bib_type = str(row.get('ENTRYTYPE', 'misc')).lower()
            f.write(f'TY  - {TYPE_MAPPING.get(bib_type, "GEN")}\n')
            
            # Cleaning fields for Covidence stability
            for field, tag in [('title', 'TI'), ('abstract', 'AB'), ('year', 'PY'), ('url', 'UR'), ('doi', 'DO')]:
                val = str(row.get(field, '')).replace('{', '').replace('}', '').replace('\n', ' ').strip()
                if val and val != 'nan':
                    f.write(f"{tag}  - {val}\n")
            
            # Author mapping
            authors = str(row.get('author', '')).replace('\n', ' ').split(' and ')
            for author in authors:
                if author.strip() and author.strip() != 'nan':
                    f.write(f"AU  - {author.strip()}\n")
            
            # Venue (Journal/Conference)
            venue = row.get('journal') or row.get('booktitle') or row.get('series')
            if pd.notna(venue):
                f.write(f"T2  - {str(venue).replace('{', '').replace('}', '').strip()}\n")
            
            f.write('ER  - \n\n')

# --- 3. MAIN EXECUTION ---

def main():
    bib_files = glob.glob(INPUT_FILE_PATTERN)
    if not bib_files: return
    
    all_entries = []
    for bib_file in bib_files:
        with open(bib_file, 'r', encoding='utf-8') as f:
            db = bibtexparser.load(f, parser=BibTexParser(common_strings=True))
            for entry in db.entries:
                entry['source_file'] = bib_file
                all_entries.append(entry)
    
    df = pd.DataFrame(all_entries)
    if df.empty: return

    df['search_text'] = (df['title'].fillna('') + ' ' + df.get('abstract', pd.Series(['']*len(df))).fillna('')).astype(str)

    # Filter logic
    mask = df['search_text'].str.contains(pattern_sufficient, na=False) | \
           (df['search_text'].str.contains(pattern_conditional, na=False) & \
            df['search_text'].str.contains(pattern_context, na=False))
    
    df_inc, df_exc = df[mask], df[~mask]
    
    print(f"Total: {len(df)} | Kept: {len(df_inc)} | Excluded: {len(df_exc)}")

    for source, group in df_inc.groupby('source_file'):
        write_df_to_ris(group, f"agg_sok_{os.path.basename(source).replace('.bib', '.ris')}")

    df_exc[['title', 'source_file']].to_csv(OUTPUT_REJECTED_FILE, index=False)

if __name__ == "__main__":
    main()