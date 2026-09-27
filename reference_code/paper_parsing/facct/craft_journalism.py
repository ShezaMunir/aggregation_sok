import bibtexparser
import csv
import os

def process_and_export_facct_data(file_pattern, years, output_filename="facct_journalism_ai.csv"):
    """
    Parses BibTeX files for Journalism/AI research and exports to a structured CSV.
    """
    relevant_entries = []
    unique_authors = set()
    
    # Taxonomic keywords for filtering
    keywords = ['journalism', 'news', 'media', 'reporter', 'editorial', 'press', 'fact-check']
    
    for year in years:
        file_path = file_pattern.format(year=year)
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, 'r', encoding='utf-8') as bibfile:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_database = bibtexparser.load(bibfile, parser=parser)
            
            for entry in bib_database.entries:
                # Aggregate title and abstract for comprehensive keyword scanning
                title = entry.get('title', '')
                abstract = entry.get('abstract', '')
                content = (title + " " + abstract).lower()
                
                if any(kw in content for kw in keywords):
                    relevant_entries.append(entry)
                    
                    # Author normalization
                    authors_raw = entry.get('author', '').split(' and ')
                    for auth in authors_raw:
                        clean_auth = auth.strip().replace('{', '').replace('}', '')
                        if clean_auth:
                            unique_authors.add(clean_auth)

    # Define CSV Headers based on requested fields
    headers = ['ID', 'Year', 'Title', 'Author', 'Abstract', 'DOI', 'URL']
    
    with open(output_filename, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        
        for entry in relevant_entries:
            writer.writerow({
                'ID': entry.get('ID', 'N/A'),
                'Year': entry.get('year', 'N/A'),
                'Title': entry.get('title', 'N/A'),
                'Author': entry.get('author', 'N/A'),
                'Abstract': entry.get('abstract', 'N/A'),
                'DOI': entry.get('doi', 'N/A'),
                'URL': entry.get('url', 'N/A')
            })

    return len(relevant_entries), sorted(list(unique_authors))

# Configuration and Execution
bib_years = [2020, 2021, 2022, 2023, 2024, 2025]
file_template = "facct_{year}.bib"

paper_count, author_list = process_and_export_facct_data(file_template, bib_years)

print(f"Data Processing Complete.")
print(f"Total relevant entries exported: {paper_count}")
print(f"A total of {len(author_list)} unique contributors were identified.")