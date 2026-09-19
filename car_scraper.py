import os
import json
import csv
import re
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Configuration and Environment Setup
MAX_PAGES = int(os.environ.get("MAX_PAGES", "3"))  # Pages to scrape per target URL [1]
CACHE_FILE = "seen_cars.json"
CSV_FILE = "results.csv"
URLS_FILE = "urls.txt"

# Default fallback URL wrapped in valid string quotes
DEFAULT_URLS = [
    "https://www.kleinanzeigen.de/s-autos/muenchen/sortierung:neuste/anbieter:privat/anzeige:angebote/preis::7000/c216l6411r30+autos.anzahl_tueren_s:4_5+autos.km_i:%2C125000+autos.schaden_s:nein+autos.tuevy_i:2028+autos.umweltplakette_s:4_gruen"
]

def get_driver():
    """Initialize Headless Chrome WebDriver."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=options)

def dismiss_cookie_banners(driver):
    """Auto-dismiss GDPR cookie consent popups across target platforms [2]."""
    cookie_button_ids = [
        "gdpr-banner-accept",
        "accept-privacy-consent",
        "uc-btn-accept-banner",
        "onetrust-accept-btn-handler"
    ]
    for btn_id in cookie_button_ids:
        try:
            btns = driver.find_elements(By.ID, btn_id)
            if btns:
                driver.execute_script("arguments.click();", btns)
                time.sleep(1)
                break
        except Exception:
            pass

def fetch_full_description(driver, listing_url):
    """Navigate to ad detail page and extract seller text from id='viewad-description-text' [3]."""
    try:
        driver.get(listing_url)
        time.sleep(2)
        dismiss_cookie_banners(driver)
        soup = BeautifulSoup(driver.page_source, "html.parser")

        desc_elem = soup.find(id="viewad-description-text") or soup.find("div", id="viewad-description-text")
        if desc_elem:
            return desc_elem.text.strip().replace("\n", " ")
    except Exception as e:
        print(f"      [Warning] Could not fetch detail page description: {e}")
    return ""

def load_seen_cars():
    """Load cached listing IDs from seen_cars.json [1]."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_seen_cars(seen_ids):
    """Save updated listing IDs back to cache [1]."""
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_ids), f, indent=2)

def load_target_urls():
    """Read search URLs from urls.txt or fallback to DEFAULT_URLS [1]."""
    urls = []
    if os.path.exists(URLS_FILE):
        with open(URLS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    return urls if urls else DEFAULT_URLS

def scrape_kleinanzeigen(driver, base_url, max_pages, seen_ids):
    """Scrape Multi-page Kleinanzeigen listings [4]."""
    listings = []
    page_count = 0
    current_url = base_url

    while current_url and page_count < max_pages:
        page_count += 1
        print(f"   [Kleinanzeigen] Scraping Page {page_count}: {current_url}")
        driver.get(current_url)
        time.sleep(3)
        dismiss_cookie_banners(driver)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        articles = soup.find_all("article", class_="aditem") or soup.select("article[data-adid]") or soup.select(".ad-listitem")
        print(f"   Found {len(articles)} listing(s) on Page {page_count}.")

        for article in articles:
            ad_id = article.get("data-adid")
            if not ad_id:
                link_elem = article.find("a", href=True)
                if link_elem:
                    id_match = re.search(r"/(\d{8,12})", link_elem["href"])
                    if id_match:
                        ad_id = id_match.group(1)
            if not ad_id:
                continue

            is_new = ad_id not in seen_ids

            title_elem = article.find("a", class_="ellipsis") or article.select_one("h2 a") or article.find("a", href=True)
            price_elem = article.find("p", class_="aditem-main--middle--price-shipping--price") or article.select_one("[class*='price']")
            img_elem = article.find("img")

            title = title_elem.text.strip() if title_elem else "Unclassified Deal"
            price_str = price_elem.text.strip() if price_elem else "N/A"
            href = title_elem.get("href") if title_elem and title_elem.get("href") else ""
            link = "https://www.kleinanzeigen.de" + href if href.startswith("/") else href
            image_url = img_elem.get("src") or img_elem.get("data-imgsrc", "") if img_elem else ""

            snippet_desc = article.find("p", class_="aditem-main--middle--description")
            description = snippet_desc.text.strip().replace("\n", " ") if snippet_desc else ""

            # Fetch full seller description text for newly discovered ads [4]
            if is_new and link:
                print(f"      Fetching full detail description for ad {ad_id}...")
                full_desc = fetch_full_description(driver, link)
                if full_desc:
                    description = full_desc

            # Parse numeric price
            price_num = "".join(filter(str.isdigit, price_str)) or "0"

            item = {
                "id": ad_id,
                "platform": "kleinanzeigen",
                "title": title,
                "price": price_str,
                "price_numeric": price_num,
                "location": "München",
                "date_posted": time.strftime("%Y-%m-%d"),
                "description": description,
                "link": link,
                "image_url": image_url,
                "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            listings.append(item)
            seen_ids.add(ad_id)

        # Pagination handler
        next_page = soup.find("a", class_="pagination-next") or soup.select_one("a[rel='next']")
        if next_page and next_page.get("href"):
            next_href = next_page.get("href")
            current_url = "https://www.kleinanzeigen.de" + next_href if next_href.startswith("/") else next_href
        elif "/seite:" not in current_url:
            current_url = re.sub(r'(/s-autos/[^/]+)', r'\1/seite:' + str(page_count + 1), base_url)
        else:
            current_url = re.sub(r'/seite:\d+', f'/seite:{page_count + 1}', current_url)

    return listings

def save_results_to_csv(listings, filename=CSV_FILE):
    """Append scraped listings to CSV [1]."""
    file_exists = os.path.exists(filename)
    fieldnames = ["id", "platform", "title", "price", "price_numeric", "location", "date_posted", "description", "link", "image_url", "scraped_at"]
    
    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists or os.stat(filename).st_size == 0:
            writer.writeheader()
        for item in listings:
            writer.writerow(item)

def main():
    print("Starting Multi-Platform Car Scraper...")
    seen_ids = load_seen_cars()
    target_urls = load_target_urls()
    driver = get_driver()
    all_listings = []

    try:
        for url in target_urls:
            if "kleinanzeigen" in url:
                listings = scrape_kleinanzeigen(driver, url, MAX_PAGES, seen_ids)
                all_listings.extend(listings)
        
        save_results_to_csv(all_listings)
        save_seen_cars(seen_ids)
        print(f"Scraping complete. Processed {len(all_listings)} listings.")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()