import re
import pandas as pd
import os
import glob

# --- CONFIGURATION & KEYWORDS ---

# 1. SUFFICIENT Keywords (Strong Signals)
sufficient_kw = [
    # Core Annotation
    r"\bannotat", r"\blabell?ing", r"ground truth", r"gold standard",
    r"reference standard", r"human-generated", "dataset",

    # Strong Actors
    r"crowdwork", r"crowdsourc", r"\brater", r"\bcoder", r"human-in-the-loop",
    r"\bSME\b", # Subject Matter Expert

    # Strong Method/Metrics
    r"label noise", r"noisy label", r"inter-annotator", r"inter-rater",
    r"\bIAA\b", r"dawid-skene", r"\bGLAD\b", r"\bMACE\b", r"weak supervision",

    # Modern / LLM Specific
    r"\bRLHF\b", r"human feedback", r"preference optimization", r"instruction tuning",
    r"judging", r"auto-evaluat"
]

# 2. CONDITIONAL Keywords (Weak Signals)
conditional_kw = [
    r"aggregation", r"consensus", r"adjudication", r"reconciliation",
    r"rationale", r"justification", r"ambiguity", r"subjectiv",
    r"disagreement", r"bias", r"multi-perspective", r"pluralis"
]

# 3. CONTEXT Keywords
context_kw = [
    r"\blabel", r"tag", r"human", r"worker", r"rater", r"judge",
    r"annotation", r"instruction"
]

# Compile Regex Patterns
pattern_sufficient = re.compile("|".join(sufficient_kw), flags=re.IGNORECASE)
pattern_conditional = re.compile("|".join(conditional_kw), flags=re.IGNORECASE)
pattern_context = re.compile("|".join(context_kw), flags=re.IGNORECASE)


# --- HELPER FUNCTIONS ---

def clean_authors(author_str):
    """
    Converts BibTeX authors (Last, First and ...) to readable CSV format (First Last; ...).
    """
    if not author_str:
        return ""
    
    authors = author_str.split(' and ')
    cleaned_list = []
    
    for auth in authors:
        if ',' in auth:
            parts = auth.split(',', 1)
            last = parts[0].strip()
            first = parts[1].strip()
            cleaned_list.append(f"{first} {last}")
        else:
            cleaned_list.append(auth.strip())
            
    return "; ".join(cleaned_list)

def parse_bibtex_file(filename):
    """
    Parses a BibTeX file manually to handle nested braces in abstracts.
    """
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by entry start
    raw_entries = re.split(r'@inproceedings\s*\{', content)
    entries = []

    for raw in raw_entries[1:]:  # Skip the first split
        entry_data = {}
        cursor = 0
        n = len(raw)
        
        while cursor < n:
            match = re.search(r'(\w+)\s*=\s*\{', raw[cursor:])
            if not match:
                break
            
            key = match.group(1).lower()
            start_value = cursor + match.end()
            
            brace_count = 1
            value_end = start_value
            
            while brace_count > 0 and value_end < n:
                char = raw[value_end]
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                value_end += 1
            
            value = raw[start_value : value_end-1]
            value = " ".join(value.split()) # Clean whitespace
            
            entry_data[key] = value
            cursor = value_end

        if entry_data:
            entries.append(entry_data)

    return entries

def apply_goldilocks_filter(df):
    """
    Applies the keyword filtering logic to a DataFrame.
    """
    if df.empty:
        return df

    # Prepare search text
    df['search_text'] = (df['title'].astype(str).fillna('') + ' ' + 
                         df['abstract'].astype(str).fillna(''))

    # Logic 1: Strong Signal
    match_sufficient = df['search_text'].str.contains(pattern_sufficient, na=False)

    # Logic 2: Weak Signal + Context
    match_cond_term = df['search_text'].str.contains(pattern_conditional, na=False)
    match_context = df['search_text'].str.contains(pattern_context, na=False)
    match_conditional = match_cond_term & match_context

    # Combine
    final_filter = match_sufficient | match_conditional

    filtered_df = df[final_filter].drop(columns=['search_text'])
    return filtered_df


# --- MAIN PIPELINE ---

def main():
    # 1. Find Files
    bib_files = glob.glob('eaamo_*.bib')
    
    if not bib_files:
        print("No files matching 'eaamo_*.bib' found in the current directory.")
        return

    all_filtered_dfs = []
    
    print(f"Found {len(bib_files)} BibTeX files. Starting processing...\n")
    print(f"{'YEAR':<6} | {'TOTAL':<8} | {'FILTERED':<10} | {'STATUS'}")
    print("-" * 45)

    for input_file in bib_files:
        # 2. Extract Year
        match_year = re.search(r'eaamo_(\d{4})\.bib', input_file)
        if match_year:
            year = match_year.group(1)
        else:
            print(f"????   | Skipped  | Unknown    | Filename format error: {input_file}")
            continue

        # 3. Parse BibTeX
        entries = parse_bibtex_file(input_file)
        
        if not entries:
            print(f"{year:<6} | 0        | 0          | Empty file")
            continue

        # 4. Process Entries
        processed_entries = []
        for entry in entries:
            abstract = entry.get('abstract', '')
            if not abstract or not abstract.strip():
                # Optional: Print warning for missing abstract
                # print(f"Warning: No abstract for '{entry.get('title')}' in {year}")
                pass
            
            entry['year'] = year
            processed_entries.append(entry)

        # 5. Create Raw DataFrame
        df = pd.DataFrame(processed_entries)

        # Standardize Columns
        target_cols = ['year', 'title', 'author', 'abstract', 'url']
        available_cols = [c for c in target_cols if c in df.columns]
        df = df[available_cols]

        if 'author' in df.columns:
            df['author'] = df['author'].apply(clean_authors)
            df.rename(columns={'author': 'authors'}, inplace=True)

        final_cols = ['year', 'title', 'authors', 'abstract', 'url']
        for c in final_cols:
            if c not in df.columns:
                df[c] = ""
        df = df[final_cols]

        # 6. Save RAW CSV
        raw_csv_name = f"eaamo_{year}.csv"
        df.to_csv(raw_csv_name, index=False)

        # 7. Apply Filtering
        filtered_df = apply_goldilocks_filter(df)
        
        # 8. Report Stats
        total_count = len(df)
        filtered_count = len(filtered_df)
        print(f"{year:<6} | {total_count:<8} | {filtered_count:<10} | Processed & Saved")

        if not filtered_df.empty:
            all_filtered_dfs.append(filtered_df)

    # 9. Combine and Save Final Filtered CSV
    print("-" * 45)
    if all_filtered_dfs:
        combined_df = pd.concat(all_filtered_dfs, ignore_index=True)
        
        # Sort by year descending
        combined_df = combined_df.sort_values(by='year', ascending=False)
        
        output_filename = "eaamo_filtered_combined.csv"
        combined_df.to_csv(output_filename, index=False)
        
        print(f"Done! Combined filtered papers: {len(combined_df)}")
        print(f"Saved to: {output_filename}")
    else:
        print("Done! No papers passed the filter criteria across all years.")

if __name__ == "__main__":
    main()