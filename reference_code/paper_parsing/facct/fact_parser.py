import time
import re
import pandas as pd
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION: The Standard URLs ---
# We keep the standard URLs here. The script will rewrite them later if needed.
FACCT_YEARS = {
    "2024": "https://dl.acm.org/doi/proceedings/10.1145/3630106",
    "2023": "https://dl.acm.org/doi/proceedings/10.1145/3593013",
    "2022": "https://dl.acm.org/doi/proceedings/10.1145/3531146",
    "2021": "https://dl.acm.org/doi/proceedings/10.1145/3442188",
    "2020": "https://dl.acm.org/doi/proceedings/10.1145/3351095",
    # "2019": "https://dl.acm.org/doi/proceedings/10.1145/3287560", # Formerly FAT*
    # "2018": "https://dl.acm.org/doi/proceedings/10.1145/3278721"  # Formerly FAT*
}

def setup_driver():
    """
    Initializes the Chrome browser with options suitable for scraping.
    """
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    # We DO NOT use headless mode because you need to see the screen to login to UofT.
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver

def rewrite_url_for_proxy(original_url, current_base_url):
    """
    Dynamically rewrites a standard ACM URL to match the user's active proxy session.
    
    Args:
        original_url (str): The standard URL (e.g., https://dl.acm.org/...)
        current_base_url (str): The URL the browser is currently on (e.g., https://dl-acm-org.myaccess...)
    
    Returns:
        str: The rewritten URL compatible with the active session.
    """
    parsed_current = urlparse(current_base_url)
    parsed_original = urlparse(original_url)
    
    # If the domains match, no rewriting needed
    if parsed_current.netloc == parsed_original.netloc:
        return original_url
        
    # Construct new URL: Scheme + Proxy Netloc + Original Path
    new_url = urlunparse((
        parsed_current.scheme,
        parsed_current.netloc,
        parsed_original.path,
        parsed_original.params,
        parsed_original.query,
        parsed_original.fragment
    ))
    return new_url

def get_paper_details(driver, paper_url):
    """
    Visits a specific paper page to extract high-fidelity metadata.
    """
    try:
        driver.get(paper_url)
        # Random sleep to mimic human reading and avoid rate limits
        time.sleep(3) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 1. Title Extraction
        title_tag = soup.find('h1', class_='citation__title')
        title = title_tag.text.strip() if title_tag else "N/A"
        
        # 2. Author Extraction
        # ACM lists authors in spans with class 'oa-author-name' or 'author-name'
        authors = []
        author_tags = soup.find_all('span', class_='oa-author-name')
        if not author_tags:
            # Fallback for older layouts
            author_tags = soup.find_all('span', class_='author-name')
            
        for auth in author_tags:
            authors.append(auth.text.strip())
        authors_str = "; ".join(authors)
        
        # 3. Abstract Extraction
        # We look for the abstract section specifically to avoid grabbing other text.
        abstract_text = "No Abstract Found"
        
        # Method A: Standard Abstract Section
        abs_section = soup.find('div', class_='abstractSection')
        if abs_section:
            # Remove the word "Abstract" if it appears as a header inside the div
            abstract_text = abs_section.text.replace('Abstract', '', 1).strip()
        
        # Method B: Meta tag fallback (sometimes cleaner)
        if abstract_text == "No Abstract Found":
            meta_desc = soup.find('meta', attrs={'name': 'Description'})
            if meta_desc:
                abstract_text = meta_desc['content']

        return {
            "Title": title,
            "Authors": authors_str,
            "Abstract": abstract_text,
            "URL": paper_url
        }

    except Exception as e:
        print(f"Failed to scrape {paper_url}: {e}")
        return None

def main():
    driver = setup_driver()
    
    # --- PHASE 1: LOGIN HANDSHAKE ---
    print("=================================================")
    print("Initiating UofT Access Sequence")
    print("1. Browser will open.")
    print("2. You have 60 seconds to log in via UTORid.")
    print("3. Ensure you end up on the ACM Digital Library homepage.")
    print("=================================================")
    
    # We navigate to the UofT library proxy login for ACM directly to help you
    # This is the standard UofT proxy link for ACM DL
    driver.get("http://myaccess.library.utoronto.ca/login?url=https://dl.acm.org")
    
    time.sleep(60) # Giving you time to do 2FA and load the page
    
    # --- PHASE 2: SESSION DETECTION ---
    current_url = driver.current_url
    print(f"Login time over. Detected current URL: {current_url}")
    
    if "myaccess.library.utoronto.ca" in current_url:
        print("SUCCESS: Proxy session detected.")
    else:
        print("WARNING: You do not appear to be on the UofT proxy domain.")
        print("Continuing anyway, but access may be denied.")

    # --- PHASE 3: THE SCRAPING LOOP ---
    all_papers_data = []
    
    for year, standard_url in FACCT_YEARS.items():
        print(f"\n--- Starting Collection: FAccT {year} ---")
        
        # Rewrite the URL to match your current session (Proxy or Standard)
        target_url = rewrite_url_for_proxy(standard_url, current_url)
        print(f"Navigating to: {target_url}")
        
        driver.get(target_url)
        time.sleep(5) # Wait for proceedings page to load
        
        # Parse the Proceedings List
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Find all individual paper links
        # ACM usually links papers inside <h5 class="issue-item__title"><a href="...">
        paper_links = []
        items = soup.find_all('h5', class_='issue-item__title')
        
        for item in items:
            a_tag = item.find('a')
            if a_tag and 'href' in a_tag.attrs:
                # The href is relative (e.g., /doi/10.1145/...). 
                # We must construct the full URL using the PROXY domain.
                # 'driver.current_url' gives us the base, but we need the root.
                
                parsed_base = urlparse(driver.current_url)
                base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
                
                full_link = base_domain + a_tag['href']
                paper_links.append(full_link)
        
        print(f"Found {len(paper_links)} papers. Beginning extraction...")
        
        year_data = []
        for i, link in enumerate(paper_links):
            print(f"[{year}] Processing {i+1}/{len(paper_links)}")
            
            paper_info = get_paper_details(driver, link)
            
            if paper_info:
                paper_info['Year'] = year
                year_data.append(paper_info)
            
            # Save progress every 10 papers in case of crash
            if (i + 1) % 10 == 0:
                temp_df = pd.DataFrame(year_data)
                temp_df.to_csv(f"./partial/facct_{year}_partial.csv", index=False)

        # Final Save for the Year
        df = pd.DataFrame(year_data)
        final_filename = f"facct_{year}_final.csv"
        df.to_csv(final_filename, index=False)
        print(f"Completed {year}. Saved to {final_filename}")

    driver.quit()
    print("Pipeline Execution Finished.")

if __name__ == "__main__":
    main()