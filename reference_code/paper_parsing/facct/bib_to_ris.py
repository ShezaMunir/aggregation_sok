import bibtexparser
from bibtexparser.bparser import BibTexParser

def bibtex_to_ris(input_bib_path, output_ris_path):
    """
    Converts a BibTeX file to a RIS file.
    """
    
    # map BibTeX entry types to RIS types
    # (Keys are BibTeX, Values are RIS)
    TYPE_MAPPING = {
        'article': 'JOUR',
        'book': 'BOOK',
        'inproceedings': 'CONF',
        'conference': 'CONF',
        'phdthesis': 'THES',
        'mastersthesis': 'THES',
        'techreport': 'RPRT',
        'misc': 'GEN',
        'unpublished': 'UNPB'
    }

    # Open and parse the BibTeX file
    with open(input_bib_path, 'r', encoding='utf-8') as bib_file:
        parser = BibTexParser(common_strings=True)
        bib_database = bibtexparser.load(bib_file, parser=parser)

    # Write to the RIS file
    with open(output_ris_path, 'w', encoding='utf-8') as ris_file:
        
        for entry in bib_database.entries:
            # 1. Determine Type (TY)
            bib_type = entry.get('ENTRYTYPE', 'misc').lower()
            ris_type = TYPE_MAPPING.get(bib_type, 'GEN') # Default to Generic if unknown
            ris_file.write(f'TY  - {ris_type}\n')

            # 2. Title (TI)
            if 'title' in entry:
                # Remove common BibTeX braces {} meant for capitalization protection
                clean_title = entry['title'].replace('{', '').replace('}', '')
                ris_file.write(f'TI  - {clean_title}\n')

            # 3. Authors (AU)
            if 'author' in entry:
                # BibTeX separates authors with ' and '
                authors = entry['author'].split(' and ')
                for author in authors:
                    # formatting usually handles "Last, First" automatically, 
                    # but stripping whitespace is safe.
                    ris_file.write(f'AU  - {author.strip()}\n')

            # 4. Year (PY)
            if 'year' in entry:
                ris_file.write(f"PY  - {entry['year']}\n")

            # 5. Container/Journal (JO/T2)
            if 'journal' in entry:
                ris_file.write(f"JO  - {entry['journal']}\n")
            elif 'booktitle' in entry:
                ris_file.write(f"T2  - {entry['booktitle']}\n")

            # 6. Volume (VL) and Issue (IS)
            if 'volume' in entry:
                ris_file.write(f"VL  - {entry['volume']}\n")
            if 'number' in entry:
                ris_file.write(f"IS  - {entry['number']}\n")

            # 7. Pages (SP/EP)
            if 'pages' in entry:
                # RIS prefers Start Page (SP) and End Page (EP) separated
                pages = entry['pages'].replace('--', '-').split('-')
                if len(pages) > 0:
                    ris_file.write(f"SP  - {pages[0]}\n")
                if len(pages) > 1:
                    ris_file.write(f"EP  - {pages[1]}\n")

            # 8. Publisher (PB)
            if 'publisher' in entry:
                ris_file.write(f"PB  - {entry['publisher']}\n")

            # 9. DOI (DO) and URL (UR)
            if 'doi' in entry:
                ris_file.write(f"DO  - {entry['doi']}\n")
            if 'url' in entry:
                ris_file.write(f"UR  - {entry['url']}\n")
            
            # 10. Abstract (AB)
            if 'abstract' in entry:
                ris_file.write(f"AB  - {entry['abstract']}\n")

            # End of Record
            ris_file.write('ER  - \n\n')

    print(f"Successfully converted {len(bib_database.entries)} entries to {output_ris_path}")

# --- usage ---
# Replace 'references.bib' with your file name
bibtex_to_ris('acm_2025.bib', '2025_facct.ris')