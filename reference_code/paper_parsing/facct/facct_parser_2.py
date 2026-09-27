import time
import pandas as pd
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
FACCT_YEARS = {
    "2025": "https://dl.acm.org/doi/proceedings/10.1145/3715275",
    "2024": "https://dl.acm.org/doi/proceedings/10.1145/3630106",
    "2023": "https://dl.acm.org/doi/proceedings/10.1145/3593013",
    "2022": "https://dl.acm.org/doi/proceedings/10.1145/3531146",
    "2021": "https://dl.acm.org/doi/proceedings/10.1145/3442188",
    "2020": "https://dl.acm.org/doi/proceedings/10.1145/3351095",
}

def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    options.add_argument('--disable-blink-features=AutomationControlled')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver

def rewrite_url_for_proxy(original_url, current_base_url):
    """Rewrites standard URL to match the active Proxy Domain."""
    parsed_current = urlparse(current_base_url)
    parsed_original = urlparse(original_url)
    if parsed_current.netloc == parsed_original.netloc:
        return original_url
    new_url = urlunparse((
        parsed_current.scheme,
        parsed_current.netloc,
        parsed_original.path,
        parsed_original.params,
        parsed_original.query,
        parsed_original.fragment
    ))
    return new_url

def scroll_page(driver):
    """Slowly scrolls the page to trigger lazy loading images/links."""
    total_height = int(driver.execute_script("return document.body.scrollHeight"))
    for i in range(1, total_height, 700):
        driver.execute_script(f"window.scrollTo(0, {i});")
        time.sleep(0.5)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

def get_paper_details(driver, paper_url):
    try:
        driver.get(paper_url)
        # Wait for title to ensure page load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # TITLE
        title_tag = soup.find('h1', class_='citation__title')
        title = title_tag.text.strip() if title_tag else "N/A"
        
        # AUTHORS
        authors = []
        author_tags = soup.find_all('span', class_='oa-author-name')
        if not author_tags: # Fallback
            author_tags = soup.find_all('span', class_='author-name')
        for auth in author_tags:
            authors.append(auth.text.strip())
        authors_str = "; ".join(authors)
        
        # ABSTRACT
        abstract_text = "No Abstract Found"
        abs_section = soup.find('div', class_='abstractSection')
        if abs_section:
            abstract_text = abs_section.text.replace('Abstract', '', 1).strip()
        else:
            meta = soup.find('meta', attrs={'name': 'Description'})
            if meta:
                abstract_text = meta['content']

        return {"Title": title, "Authors": authors_str, "Abstract": abstract_text, "URL": paper_url}

    except Exception as e:
        print(f"Error scraping {paper_url}: {e}")
        return None

def main():
    driver = setup_driver()
    
    # --- LOGIN PHASE ---
    print("=========================================")
    print("OPENING BROWSER. PLEASE LOGIN TO UofT.")
    print("=========================================")
    driver.get("http://myaccess.library.utoronto.ca/login?url=https://dl.acm.org")
    
    time.sleep(60) # Time for manual login
    
    current_url = driver.current_url
    print(f"Detected Session URL: {current_url}")

    # --- SCRAPING PHASE ---
    for year, standard_url in FACCT_YEARS.items():
        print(f"\n--- Processing FAccT {year} ---")
        
        target_url = rewrite_url_for_proxy(standard_url, current_url)
        driver.get(target_url)
        
        print("Page loaded. Scrolling to trigger paper list...")
        scroll_page(driver)
        
        # Wait for the issue items to appear
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CLASS_NAME, "issue-item"))
            )
            print("Paper list detected in DOM!")
        except:
            print("WARNING: Timeout waiting for 'issue-item'. Page might not have loaded correctly.")

        # Parse with BS4
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Find all 'issue-item' blocks
        # ACM structure: <div class="issue-item ..."> -> <h5 class="issue-item__title"><a href="...">
        paper_links = []
        items = soup.find_all(class_='issue-item__title')
        
        for item in items:
            a_tag = item.find('a')
            if a_tag and 'href' in a_tag.attrs:
                href = a_tag['href']
                
                # Construct full URL
                if href.startswith("http"):
                    full_link = href
                else:
                    parsed_base = urlparse(driver.current_url)
                    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
                    if not href.startswith('/'):
                        href = '/' + href
                    full_link = base_domain + href
                
                paper_links.append(full_link)
        
        # Deduplicate
        paper_links = list(set(paper_links))
        print(f"Found {len(paper_links)} papers for {year}.")
        
        # --- SAFEGUARD: IF 0 PAPERS, DUMP HTML ---
        if len(paper_links) == 0:
            print("!!! CRITICAL FAILURE: 0 PAPERS FOUND !!!")
            with open(f"debug_fail_{year}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print(f"Saved page source to 'debug_fail_{year}.html'. Please inspect it.")
            continue # Skip to next year

        # Extract Details
        year_data = []
        for i, link in enumerate(paper_links):
            print(f"[{i+1}/{len(paper_links)}] Scraping details...")
            details = get_paper_details(driver, link)
            if details:
                details['Year'] = year
                year_data.append(details)
            
            # Save partial
            if i > 0 and i % 10 == 0:
                pd.DataFrame(year_data).to_csv(f"facct_{year}_partial.csv", index=False)
                
        # Final Save
        if year_data:
            pd.DataFrame(year_data).to_csv(f"facct_{year}_final.csv", index=False)
            print(f"Saved {len(year_data)} papers for {year}.")

    driver.quit()

if __name__ == "__main__":
    main()