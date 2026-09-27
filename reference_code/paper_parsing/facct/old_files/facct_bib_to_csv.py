import re
import pandas as pd
import os
import glob

def clean_authors(author_str):
    """
    Converts BibTeX authors to a readable CSV format.
    Input: "Ingber, Alexis Shore and Andalibi, Nazanin"
    Output: "Alexis Shore Ingber; Nazanin Andalibi"
    """
    if not author_str:
        return ""
    
    # Split by ' and ' to get individual authors
    authors = author_str.split(' and ')
    cleaned_list = []
    
    for auth in authors:
        if ',' in auth:
            # Split "Last, First" -> ["Last", "First"]
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

    # Regex to find the start of each entry
    # We look for @inproceedings{ID, ...
    raw_entries = re.split(r'@inproceedings\s*\{', content)
    entries = []

    for raw in raw_entries[1:]:  # Skip the first split (empty or header)
        entry_data = {}
        
        # Manually parse fields to handle nested braces safely
        cursor = 0
        n = len(raw)
        
        while cursor < n:
            # Find the next key-value pair
            # Match word = {
            match = re.search(r'(\w+)\s*=\s*\{', raw[cursor:])
            if not match:
                break
            
            key = match.group(1).lower()
            start_value = cursor + match.end()
            
            # Walk through the string counting braces to find the matching closing brace
            brace_count = 1
            value_end = start_value
            
            while brace_count > 0 and value_end < n:
                char = raw[value_end]
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                value_end += 1
            
            # Extract value (minus the last closing brace)
            value = raw[start_value : value_end-1]
            
            # Clean up newlines and excessive whitespace in abstract/title
            value = " ".join(value.split())
            
            entry_data[key] = value
            cursor = value_end

        # Only add if we successfully parsed data
        if entry_data:
            entries.append(entry_data)

    return entries

def main():
    # Find all bib files matching the pattern acm_YYYY.bib
    bib_files = glob.glob('acm_*.bib')
    
    if not bib_files:
        print("No files matching 'acm_*.bib' found in the current directory.")
        return

    for input_file in bib_files:
        # 1. Extract Year from Filename
        # Matches '2025' from 'acm_2025.bib'
        match_year = re.search(r'acm_(\d{4})\.bib', input_file)
        if match_year:
            year = match_year.group(1)
        else:
            print(f"Skipping {input_file}: Filename must contain a year (e.g., acm_2025.bib)")
            continue

        print(f"\nProcessing: {input_file} (Year: {year})")
        entries = parse_bibtex_file(input_file)
        
        if not entries:
            print(f"No entries found in {input_file}.")
            continue

        processed_entries = []

        # 2. Process Entries and Check for Missing Abstracts
        for entry in entries:
            title = entry.get('title', 'Unknown Title')
            url = entry.get('url', 'Unknown URL')
            abstract = entry.get('abstract', '')

            # Check if abstract is missing or empty
            if not abstract or not abstract.strip():
                print(f" -> NO ABSTRACT: '{title}'\n    URL: {url}\n    (This doesn't have an abstract in the bibtex)")
            
            # Force the year from the filename to ensure consistency
            entry['year'] = year
            processed_entries.append(entry)

        # 3. Create DataFrame
        df = pd.DataFrame(processed_entries)

        # Select and Reorder columns
        target_cols = ['year', 'title', 'author', 'abstract', 'url']
        available_cols = [c for c in target_cols if c in df.columns]
        df = df[available_cols]

        # Clean Authors
        if 'author' in df.columns:
            df['author'] = df['author'].apply(clean_authors)
            df.rename(columns={'author': 'authors'}, inplace=True)
            
        # Ensure all standard columns exist for CSV structure
        final_cols = ['year', 'title', 'authors', 'abstract', 'url']
        for c in final_cols:
            if c not in df.columns:
                df[c] = ""
        
        df = df[final_cols]

        # 4. Export to CSV
        output_filename = f"facct_{year}.csv"
        df.to_csv(output_filename, index=False)
        print(f"Successfully created: {output_filename} ({len(df)} papers)")

if __name__ == "__main__":
    main()