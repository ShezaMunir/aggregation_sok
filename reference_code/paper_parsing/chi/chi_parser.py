import time
import csv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ================= CONFIGURATION =================
# The base URL of the proceedings (change if needed)
TARGET_URL = "https://dl-acm-org.myaccess.library.utoronto.ca/doi/proceedings/10.1145/3313831?pageSize=1000"
OUTPUT_FILE = "chi2020_uni_scrape.bib"
# =================================================

def clean_text(text):
    """Helper to clean up messy scraped text."""
    if not text: return ""
    return text.replace('\n', ' ').replace('  ', ' ').strip()

def main():
    print("🚀 Launching Browser...")
    
    # 1. Setup Chrome Driver
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless") # Keep this commented out so you can see the login screen!
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        # 2. Go to the URL
        driver.get(TARGET_URL)
        
        print("\n" + "="*60)
        print("🛑 ACTION REQUIRED:")
        print("1. The browser has opened.")
        print("2. Log in using your University/Institution access manually in that window.")
        print("3. Navigate to the specific proceedings page you want to scrape.")
        print("4. IMPORTANT: Make sure you scroll down or change settings to 'Show All' papers.")
        print("   (Tip: Add '?pageSize=1000' to the URL to see everything on one page)")
        print("="*60 + "\n")
        
        input("👉 Press ENTER here once you are logged in and the list of papers is visible on screen...")

        print("\n🔍 Detecting papers...")
        
        # 3. Find all paper containers
        # ACM usually uses class 'issue-item-container' for each paper entry
        papers = driver.find_elements(By.CLASS_NAME, "issue-item-container")
        print(f"   Found {len(papers)} paper containers.")

        if len(papers) == 0:
            print("❌ No papers found. Are you on the right page? (e.g. Table of Contents)")
            return

        print("📝 Scraping metadata and constructing BibTeX...")
        
        bibtex_entries = []
        
        # 4. Iterate and Extract
        for i, paper in enumerate(papers):
            try:
                # --- Title ---
                title_el = paper.find_element(By.CLASS_NAME, "issue-item__title")
                title = clean_text(title_el.text)

                # --- Authors ---
                # Authors are usually in a list under aria-label="authors"
                try:
                    author_list = paper.find_elements(By.CSS_SELECTOR, 'ul[aria-label="authors"] li a')
                    authors = [clean_text(a.text) for a in author_list]
                    author_str = " and ".join(authors)
                except:
                    author_str = "Unknown"

                # --- DOI ---
                try:
                    doi_el = paper.find_element(By.CLASS_NAME, "issue-item__doi")
                    doi = clean_text(doi_el.text).replace("https://doi.org/", "")
                except:
                    doi = ""

                # --- Abstract ---
                # This is the tricky part. It might be hidden.
                abstract = ""
                try:
                    # Try to find the abstract text div
                    abs_el = paper.find_element(By.CLASS_NAME, "issue-item__abstract")
                    abstract = clean_text(abs_el.get_attribute("innerText")) # innerText gets hidden text too
                    
                    # Clean up the "Abstract" label often found at the start
                    if abstract.startswith("Abstract"):
                        abstract = abstract[8:].strip()
                except:
                    pass # No abstract found or it's not loaded

                # --- Page Numbers ---
                try:
                    pages_el = paper.find_element(By.CLASS_NAME, "issue-item__page-range")
                    pages = clean_text(pages_el.text)
                except:
                    pages = ""

                # --- Generate Cite Key ---
                # e.g., Smith2020
                first_author = authors[0].split(" ")[-1] if authors else "ACM"
                first_author = ''.join(e for e in first_author if e.isalnum()) # Remove special chars
                cite_key = f"{first_author}2020_{i}"

                # --- Build BibTeX ---
                entry = f"""@inproceedings{{{cite_key},
  title = {{{title}}},
  author = {{{author_str}}},
  booktitle = {{Proceedings of the 2020 CHI Conference on Human Factors in Computing Systems}},
  year = {{2020}},
  doi = {{{doi}}},
  pages = {{{pages}}},
  abstract = {{{abstract}}}
}}"""
                bibtex_entries.append(entry)

                # Progress indicator
                if i % 10 == 0:
                    print(f"   Processed {i}/{len(papers)}...")

            except Exception as e:
                print(f"   ⚠️ Error scraping paper #{i}: {e}")

        # 5. Save to file
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(bibtex_entries))
            
        print(f"\n✅ DONE! Saved {len(bibtex_entries)} papers to '{OUTPUT_FILE}'")

    except Exception as e:
        print(f"❌ Critical Error: {e}")
    finally:
        # Keep browser open for a few seconds then close
        time.sleep(2)
        driver.quit()

if __name__ == "__main__":
    main()