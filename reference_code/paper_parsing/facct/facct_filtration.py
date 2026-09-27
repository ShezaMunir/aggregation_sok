import pandas as pd
import re
import glob
import os

# --- CONFIGURATION ---
# We look for files named "facct_2024.csv", "facct_2023.csv", etc.
# FAccT started in 2018 (as FAT*), so we cover the full range up to 2025.
years = range(2018, 2026) 
input_pattern = "facct_{}.csv" 

# --- THE GOLDILOCKS FILTER (Exact Copy) ---

# 1. SUFFICIENT Keywords (Strong Signals)
# If a paper contains these, it is DEFINITELY relevant.
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
# These are common words. They are only relevant if they are about LABELS.
conditional_kw = [
    r"aggregation", r"consensus", r"adjudication", r"reconciliation",
    r"rationale", r"justification", r"ambiguity", r"subjectiv",
    r"disagreement", r"bias", r"multi-perspective", r"pluralis"
]

# 3. CONTEXT Keywords (The Fix)
# Words that imply the conditional keyword is about ANNOTATION.
context_kw = [
    r"\blabel", r"tag", r"human", r"worker", r"rater", r"judge",
    r"annotation", r"instruction"
]

# Compile Patterns
pattern_sufficient = re.compile("|".join(sufficient_kw), flags=re.IGNORECASE)
pattern_conditional = re.compile("|".join(conditional_kw), flags=re.IGNORECASE)
pattern_context = re.compile("|".join(context_kw), flags=re.IGNORECASE)

filtered_all_years = []

print("--- Starting Goldilocks Filtering for FAccT ---")

for year in years:
    filename = input_pattern.format(year)
    
    if not os.path.exists(filename):
        print(f"Skipping {year}: File '{filename}' not found.")
        continue

    try:
        df = pd.read_csv(filename)
        
        # Ensure abstract/title are strings to prevent errors with NaN
        df['search_text'] = (df['title'].astype(str).fillna('') + ' ' + 
                             df['abstract'].astype(str).fillna(''))

        # --- LOGIC ---
        # 1. Strong Signal? (Auto-Include)
        match_sufficient = df['search_text'].str.contains(pattern_sufficient, na=False)

        # 2. Weak Signal? (Check Context)
        # Only keep "Ambiguity" if text ALSO says "Label", "Human", etc.
        match_cond_term = df['search_text'].str.contains(pattern_conditional, na=False)
        match_context = df['search_text'].str.contains(pattern_context, na=False)
        match_conditional = match_cond_term & match_context

        # Combine
        final_filter = match_sufficient | match_conditional

        filtered_df = df[final_filter].drop(columns=['search_text'])

        print(f"{year}: Found {len(filtered_df)} papers out of {len(df)} total.")

        if not filtered_df.empty:
            filtered_all_years.append(filtered_df)
            
    except Exception as e:
        print(f"Error processing {filename}: {e}")

# Concatenate and save
if filtered_all_years:
    combined_df = pd.concat(filtered_all_years, ignore_index=True)
    
    # Sort by year (descending) for easier reading
    if 'year' in combined_df.columns:
        combined_df = combined_df.sort_values(by='year', ascending=False)
        
    output_filename = "facct_filtered_combined.csv"
    combined_df.to_csv(output_filename, index=False)
    print("------------------------------------------------")
    print(f"SUCCESS: Total Papers Saved: {len(combined_df)}")
    print(f"File saved as: {output_filename}")
else:
    print("------------------------------------------------")
    print("No papers met the criteria across all years.")