import pandas as pd
import re

def clean_key(study):
    """Creates a valid BibTeX key by removing spaces and special characters."""
    return re.sub(r'[^a-zA-Z0-9]', '', str(study))

def generate_bib():
    try:
        # Load the corpus CSV
        df = pd.read_csv('final_corpus - Corpus.csv')
        bib_entries = []

        for _, row in df.iterrows():
            # Use the 'Study' column to create the citation key (e.g., [Author 2024])
            key = clean_key(row['Study'])
            
            # Replace semicolons with ' and ' for BibTeX author format
            authors = str(row['Authors']).replace(';', ' and ')
            title = str(row['Title']).replace('"', "'")
            year = str(row['Published Year'])
            journal = str(row['Journal']) if pd.notna(row['Journal']) else ""
            doi = str(row['DOI']) if pd.notna(row['DOI']) else ""
            
            # Construct the entry
            entry = f"@article{{{key},\n"
            entry += f"  author = {{{authors}}},\n"
            entry += f"  title = {{{title}}},\n"
            entry += f"  year = {{{year}}},\n"
            if journal and journal != 'nan':
                entry += f"  journal = {{{journal}}},\n"
            if doi and doi != 'nan':
                entry += f"  doi = {{{doi}}}\n"
            entry += "}\n\n"
            
            bib_entries.append(entry)

        # Write all entries to a .bib file
        with open('references.bib', 'w', encoding='utf-8') as f:
            f.writelines(bib_entries)
        
        print(f"Success! Created 'references.bib' with {len(bib_entries)} entries.")
    except FileNotFoundError:
        print("Error: 'final_corpus - Corpus.csv' not found in the current directory.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    generate_bib()