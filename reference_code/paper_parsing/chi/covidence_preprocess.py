import bibtexparser
from bibtexparser.bparser import BibTexParser
import pandas as pd
import re
import glob
import os

# --- CONFIGURATION ---
INPUT_FILE_PATTERN = "*.bib"  # Looks for ALL .bib files in the current folder
OUTPUT_REJECTED_FILE = "rejected_papers_log.csv" # Validation log for rejected papers

# --- 1. DEFINE KEYWORDS (Updated with Professor Feedback) ---

# TIER 1: SUFFICIENT (Strong Signals)
# If a paper has these, keep it immediately.
sufficient_kw = [
    # Core Annotation Terms
    r"\bannotat", r"\blabell?ing", r"ground truth", r"gold standard",
    r"reference standard", r"human-generated", "dataset",
    
    # Actors & Labor
    r"crowdwork", r"crowdsourc", r"\brater", r"\bcoder", r"human-in-the-loop",
    r"\bSME\b", r"data work", r"invisible work", 
    
    # Method/Metrics
    r"label noise", r"noisy label", r"inter-annotator", r"inter-rater",
    r"\bIAA\b", r"dawid-skene", r"\bGLAD\b", r"\bMACE\b", r"weak supervision",
    
    # Modern / LLM Specific (Shivani's Feedback)
    r"\bRLHF\b", r"human feedback", r"preference optimization", r"instruction tuning",
    r"judging", r"auto-evaluat", r"llm-as-a-judge", r"generative annotation", 
    r"synthetic data", r"persona-based", r"model-as-annotator",

    # Theoretical/Critical Lenses (Shivani/Edith Feedback)
    r"positionality", r"epistemic justice", r"perspectivis", 
    r"soft label", r"distributional label", r"probabilistic label", r"rating indeterminacy"
]

# TIER 2: CONDITIONAL (Weak Signals)
# Needs context to be relevant.
conditional_kw = [
    r"aggregation", r"consensus", r"adjudication", r"reconciliation",
    r"rationale", r"justification", r"ambiguity", r"subjectiv",
    r"disagreement", r"bias", r"multi-perspective", r"pluralis",
    r"wage", r"labor", r"alignment", r"simulat"
]

# TIER 3: CONTEXT (The Fix)
# Words that imply the conditional keyword is about ANNOTATION.
context_kw = [
    r"\blabel", r"tag", r"human", r"worker", r"rater", r"judge",
    r"annotation", r"instruction", r"dataset"
]

# Compile Regex Patterns
pattern_sufficient = re.compile("|".join(sufficient_kw), flags=re.IGNORECASE)
pattern_conditional = re.compile("|".join(conditional_kw), flags=re.IGNORECASE)
pattern_context = re.compile("|".join(context_kw), flags=re.IGNORECASE)

# --- 2. HELPER FUNCTIONS ---

def bibtex_to_dataframe(bib_files):
    """
    Loads multiple BibTeX files and flattens them into a single Pandas DataFrame.
    """
    all_entries = []
    
    for bib_file in bib_files:
        print(f"Reading: {bib_file}...")
        try:
            with open(bib_file, 'r', encoding='utf-8') as f:
                parser = BibTexParser(common_strings=True)
                parser.ignore_nonstandard_types = False 
                bib_database = bibtexparser.load(f, parser=parser)
                
                # Add a source column so we know which file it came from
                for entry in bib_database.entries:
                    entry['source_file'] = bib_file
                    all_entries.append(entry)
        except Exception as e:
            print(f"Error reading {bib_file}: {e}")
            
    return pd.DataFrame(all_entries)

def write_df_to_ris(df, output_path):
    """
    Iterates through a DataFrame and writes a Covidence-friendly RIS file.
    """
    # Mapping: BibTeX types -> RIS types
    TYPE_MAPPING = {
        'article': 'JOUR', 'book': 'BOOK', 'inproceedings': 'CONF',
        'conference': 'CONF', 'phdthesis': 'THES', 'mastersthesis': 'THES',
        'techreport': 'RPRT', 'misc': 'GEN', 'unpublished': 'UNPB'
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        for _, row in df.iterrows():
            # 1. Type
            bib_type = str(row.get('ENTRYTYPE', 'misc')).lower()
            ris_type = TYPE_MAPPING.get(bib_type, 'GEN')
            f.write(f'TY  - {ris_type}\n')

            # 2. Title
            if pd.notna(row.get('title')):
                clean_title = str(row['title']).replace('{', '').replace('}', '')
                f.write(f'TI  - {clean_title}\n')

            # 3. Authors
            if pd.notna(row.get('author')):
                authors = str(row['author']).replace('\n', ' ').split(' and ')
                for author in authors:
                    f.write(f'AU  - {author.strip()}\n')

            # 4. Year
            if pd.notna(row.get('year')):
                f.write(f'PY  - {row["year"]}\n')

            # 5. Abstract
            if pd.notna(row.get('abstract')):
                # Simple cleanup of braces often found in BibTeX abstracts
                clean_abs = str(row["abstract"]).replace('{', '').replace('}', '')
                f.write(f'AB  - {clean_abs}\n')
            
            # 6. Publication/Venue (Journal or Booktitle)
            venue = row.get('journal') or row.get('booktitle') or row.get('series')
            if pd.notna(venue):
                clean_venue = str(venue).replace('{', '').replace('}', '')
                f.write(f'T2  - {clean_venue}\n')

            # 7. DOI/URL
            if pd.notna(row.get('doi')):
                f.write(f'DO  - {row["doi"]}\n')
            if pd.notna(row.get('url')):
                f.write(f'UR  - {row["url"]}\n')

            # End Record
            f.write('ER  - \n\n')

# --- 3. MAIN EXECUTION FLOW ---

def main():
    # A. Find Files
    bib_files = glob.glob(INPUT_FILE_PATTERN)
    if not bib_files:
        print("No .bib files found! Make sure they are in this folder.")
        return

    # B. Load Data
    print(f"\n--- Loading {len(bib_files)} BibTeX files ---")
    df = bibtex_to_dataframe(bib_files)
    
    if df.empty:
        print("No entries found in BibTeX files.")
        return

    total_papers = len(df)
    print(f"Total Papers Found: {total_papers}")

    # C. Prepare Search Text
    # Concatenate Title + Abstract + Keywords (if available) for searching
    df['search_text'] = (
        df['title'].astype(str).fillna('') + ' ' + 
        df.get('abstract', pd.Series([''] * len(df))).astype(str).fillna('') + ' ' +
        df.get('keywords', pd.Series([''] * len(df))).astype(str).fillna('')
    )

    # D. Apply Filtering Logic
    print("--- Applying Goldilocks Filter ---")
    
    # 1. Strong Signal
    match_sufficient = df['search_text'].str.contains(pattern_sufficient, na=False)
    
    # 2. Conditional Signal
    match_cond_term = df['search_text'].str.contains(pattern_conditional, na=False)
    match_context = df['search_text'].str.contains(pattern_context, na=False)
    match_conditional = match_cond_term & match_context

    # Combine
    final_mask = match_sufficient | match_conditional
    
    # Split Data
    df_included = df[final_mask].copy()
    df_excluded = df[~final_mask].copy()

    # E. Statistics for PRISMA
    included_count = len(df_included)
    excluded_count = len(df_excluded)

    print("\n" + "="*40)
    print("PRISMA REPORTING NUMBERS")
    print("="*40)
    print(f"1. Total Records Identified:     {total_papers}")
    print(f"2. Records Removed by Automation: {excluded_count}")
    print(f"3. Records Kept for Screening:    {included_count}")
    print("="*40 + "\n")

    # F. Export Files (Split by Source)
    print("--- Exporting Files ---")

    # 1. Group by the source file (e.g., "facct_2024.bib")
    grouped = df_included.groupby('source_file')

    for source_name, group_df in grouped:
        # Clean filename: "C:/path/to/facct_2024.bib" -> "filtered_facct_2024.ris"
        base_name = os.path.basename(source_name) 
        clean_name = os.path.splitext(base_name)[0]
        output_filename = f"filtered_{clean_name}.ris"
        
        print(f"• {clean_name}: {len(group_df)} papers included -> Saving to {output_filename}")
        
        write_df_to_ris(group_df, output_filename)

    # 2. Export Rejected Log (Unified)
    print(f"\nWriting rejected log to {OUTPUT_REJECTED_FILE}...")
    columns_to_save = ['ID', 'title', 'year', 'source_file']
    valid_cols = [c for c in columns_to_save if c in df_excluded.columns]
    df_excluded[valid_cols].to_csv(OUTPUT_REJECTED_FILE, index=False)

    print("\nSUCCESS! You can now upload the 'filtered_*.ris' files to Covidence.")

if __name__ == "__main__":
    main()