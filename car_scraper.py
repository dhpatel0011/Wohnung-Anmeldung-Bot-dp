import os
import json
import csv
import re
import time
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Environment Config
MAX_PAGES = int(os.environ.get("MAX_PAGES", "3"))  # Increase to 3-5 pages for 50-100+ listings
CACHE_FILE = "seen_cars.json"
CSV_FILE = "results.csv"
URLS_FILE = "urls.txt"

DEFAULT_URLS = []

def get_driver():
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
                driver.execute_script("arguments[0].click();", btns[0])
                time.sleep(1)
                break
        except Exception:
            pass

def fetch_full_description(driver, listing_url):
    """Navigate to ad detail page and extract text from id='viewad-description-text'."""
    try:
        driver.get(listing_url)
        time.sleep(2)
        dismiss_cookie_banners(driver)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Target exact Kleinanzeigen detail tag
        desc_elem = soup.find(id="viewad-description-text") or soup.find("div", id="viewad-description-text")
        if desc_elem:
            return desc_elem.text.strip().replace("\n", " ")
    except Exception as e:
        print(f"      [Warning] Could not fetch detail page description: {e}")
    return ""

def scrape_kleinanzeigen(driver, base_url, max_pages, seen_ids):
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

            # Card snippet description fallback
            snippet_desc = article.find("p", class_="aditem-main--middle--description")
            description = snippet_desc.text.strip().replace("\n", " ") if snippet_desc else ""

            # Fetch Full Detailed Description from id='viewad-description-text' for new ads
            if is_new and link:
                print(f"      Fetching full detail description for ad {ad_id}...")
                full_desc = fetch_full_description(driver, link)
                if full_desc:
                    description = full_desc

            item = {
                "id": ad_id,
                "platform": "kleinanzeigen",
                "title": title,
                "price": price_str,
                "description": description,
                "link": link,
                "image_url": image_url,
                "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "_is_new": is_new
            }
            listings.append(item)
            seen_ids.add(ad_id)

        # Pagination logic for Kleinanzeigen (handles /seite:2/, /seite:3/, etc.)
        next_page = soup.find("a", class_="pagination-next") or soup.select_one("a[rel='next']")
        if next_page and next_page.get("href"):
            next_href = next_page.get("href")
            current_url = "https://www.kleinanzeigen.de" + next_href if next_href.startswith("/") else next_href
        elif "/seite:" not in current_url:
            # Fallback manual page construction
            current_url = re.sub(r'(/s-autos/[^/]+)', r'\1/seite:' + str(page_count + 1), base_url)
        else:
            current_url = re.sub(r'/seite:\d+', f'/seite:{page_count + 1}', current_url)

    return listings
