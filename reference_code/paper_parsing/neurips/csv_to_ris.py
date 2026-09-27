import pandas as pd
import re
import glob
import os

# --- CONFIGURATION ---
INPUT_FILE_PATTERN = "*.csv"  
OUTPUT_REJECTED_FILE = "rejected_papers_log.csv"

# --- 1. REFINED AGGREGATION FILTERS (High Precision) ---

# TIER 1: SUFFICIENT (Strong Signals - Keep Immediately)
# Focus: Data Labor Platforms + Specific Aggregation Algorithms
sufficient_kw = [
    # Platforms
    r"mechanical turk", r"mturk", r"prolific", r"labelbox", r"appen", 
    r"scale ai", r"figshare", r"crowdwork", r"(?:crowdsourc(?:ed|ing)) (?:label|data|task)",
    
    # Mathematical/Procedural Aggregation
    r"dawid-skene", r"\bGLAD\b", r"\bMACE\b", r"inter-rater reliability", 
    r"weighted (?:voting|aggregation)", r"truth discovery", r"latent class analysis",
    r"aggregation (?:method|model|framework)", r"consensus (?:mechanism|method|protocol)",
    r"label aggregation", r"noise (?:model|robust)", r"gold standard (?:construction|analysis)"
]

# TIER 2: CONDITIONAL (Aggregation & Labor Mechanics)
# These terms MUST be anchored to a "Human/Label" context.
conditional_kw = [
    r"aggregation", r"consensus", r"adjudication", r"reconciliation",
    r"ambiguity", r"subjectiv", r"disagreement", r"pluralis",
    r"wage", r"labor", r"incentive", r"positionality"
]

# TIER 3: CONTEXT (Mandatory Anchor)
context_kw = [
    r"annotat(?:or|ion)", r"label(?:er|ing)", r"rater", r"coder", r"human judge", r"worker"
]

# Compile Patterns (using (?:) to avoid group warnings)
pattern_sufficient = re.compile("|".join(sufficient_kw), flags=re.IGNORECASE)
pattern_conditional = re.compile("|".join(conditional_kw), flags=re.IGNORECASE)
pattern_context = re.compile("|".join(context_kw), flags=re.IGNORECASE)

# --- 2. RIS EXPORTER ---

def write_df_to_ris(df, output_path):
    with open(output_path, 'w', encoding='utf-8') as f:
        for _, row in df.iterrows():
            f.write("TY  - JOUR\n")
            f.write(f"TI  - {row.get('title', '')}\n")
            authors = str(row.get('authors', '')).replace(';', ',').split(',')
            for au in authors:
                if au.strip(): f.write(f"AU  - {au.strip()}\n")
            f.write(f"PY  - {row.get('year', '')}\n")
            f.write(f"AB  - {row.get('abstract', '')}\n")
            f.write(f"UR  - {row.get('url', '')}\n")
            f.write("ER  - \n\n")

# --- 3. MAIN EXECUTION FLOW ---

def main():
    csv_files = glob.glob(INPUT_FILE_PATTERN)
    all_excluded = []

    for file in csv_files:
        print(f"Processing {file}...")
        df = pd.read_csv(file)
        df.columns = df.columns.str.strip().str.lower()
        
        if 'abstract' not in df.columns or 'title' not in df.columns:
            continue

        df = df.fillna('')
        df['search_text'] = (df['title'] + " " + df['abstract']).astype(str)

        # Logic
        match_sufficient = df['search_text'].str.contains(pattern_sufficient, na=False)
        match_cond_term = df['search_text'].str.contains(pattern_conditional, na=False)
        match_context = df['search_text'].str.contains(pattern_context, na=False)
        
        # Must have conditional term AND human context
        match_conditional = match_cond_term & match_context

        final_mask = match_sufficient | match_conditional
        
        df_included = df[final_mask]
        df_excluded = df[~final_mask]
        
        if not df_included.empty:
            out_name = f"agg_strict_{os.path.basename(file).replace('.csv', '.ris')}"
            write_df_to_ris(df_included, out_name)
            print(f"• Success: Kept {len(df_included)} papers (Strict Aggregation).")
        
        all_excluded.append(df_excluded[['title', 'year']])

    if all_excluded:
        pd.concat(all_excluded).to_csv(OUTPUT_REJECTED_FILE, index=False)

if __name__ == "__main__":
    main()