import os
from acl_anthology import Anthology

def collect_acl_yearly_bibtex():
    # 1. INITIALIZE THE ANTHOLOGY
    print("--- INITIALIZING ACL ANTHOLOGY DATA ---")
    anthology = Anthology.from_repo()
    
    # 2. TARGET YEARS
    years = ["2020", "2021", "2022", "2023", "2024", "2025"]
    venue_id = "acl" 

    for year in years:
        collection_id = f"{year}.{venue_id}"
        collection = anthology.collections.get(collection_id)
        
        if not collection:
            print(f"WARNING: COLLECTION {collection_id} NOT FOUND.")
            continue
            
        output_file = f"ACL_{year}_Full_Papers.bib"
        paper_count = 0
        
        with open(output_file, "w", encoding="utf-8") as f:
            print(f"--- PROCESSING {year} ---")
            
            for volume in collection.volumes():
                volume_title = volume.title.as_text().lower()
                volume_id = volume.id.lower()
                
                # FILTER: TARGET MAIN CONFERENCE LONG PAPERS
                is_full_paper_vol = any(x in volume_id or x in volume_title for x in ["main", "long"])
                
                if is_full_paper_vol:
                    print(f"   -> EXTRACTING FROM: {volume.title.as_text()}")
                    
                    for paper in volume.papers():
                        # A. GET THE BASE BIBTEX (Missing Abstract)
                        bib_entry = paper.to_bibtex()
                        
                        # B. MANUALLY ADD THE ABSTRACT FIELD
                        if paper.abstract:
                            # Convert MarkupText to string and clean up braces
                            abstract_text = paper.abstract.as_text().replace("{", "").replace("}", "")
                            
                            # Insert the abstract field before the final closing brace
                            bib_entry = bib_entry.strip()[:-1] + f",\n  abstract = {{{abstract_text}}}\n}}"
                        
                        f.write(bib_entry + "\n\n")
                        paper_count += 1
                        
        print(f"   DONE: SAVED {paper_count} PAPERS TO {output_file}\n")

if __name__ == "__main__":
    collect_acl_yearly_bibtex()