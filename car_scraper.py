import os
import json
import csv
import re
import time
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Secrets loaded from environment variables
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL")
ALERT_EMAIL2 = os.environ.get("ALERT_EMAIL2", "")

DEFAULT_SEARCH_URL = "https://www.kleinanzeigen.de/s-autos/muenchen/sortierung:neuste/anzeige:angebote/preis::7000/c216l6411r30+autos.km_i:%2C100000+autos.schaden_s:nein+autos.tuevy_i:2028+autos.umweltplakette_s:4_gruen"
URLS_FILE = "urls.txt"
CACHE_FILE = "seen_cars.json"
CSV_FILE = "results.csv"
MAX_PAGES = int(os.environ.get("MAX_PAGES", "2"))

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

def parse_numeric_price(price_str):
    if not price_str:
        return None
    clean_str = price_str.replace(".", "").replace(",", "")
    match = re.search(r"(\d+)", clean_str)
    if match:
        return int(match.group(1))
    return None

def detect_platform(url):
    domain = urlparse(url).netloc.lower()
    if "kleinanzeigen" in domain:
        return "kleinanzeigen"
    elif "mobile.de" in domain:
        return "mobile.de"
    elif "autoscout24" in domain:
        return "autoscout24"
    else:
        return domain.replace("www.", "")

def load_target_urls():
    urls = []
    if os.path.exists(URLS_FILE):
        with open(URLS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    
    # Fallback to SEARCH_URL env or DEFAULT_SEARCH_URL if urls.txt is empty or missing
    if not urls:
        env_url = os.environ.get("SEARCH_URL", "").strip()
        urls.append(env_url if env_url else DEFAULT_SEARCH_URL)
        
    return urls

def scrape_kleinanzeigen(driver, current_url):
    listings = []
    page_count = 0
    
    while current_url and page_count < MAX_PAGES:
        page_count += 1
        print(f"   [Kleinanzeigen] Page {page_count}: {current_url}")
        driver.get(current_url)
        time.sleep(4)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        articles = soup.find_all("article", class_="aditem")
        if not articles:
            articles = soup.select("article[data-adid], .ad-listitem")

        for article in articles:
            ad_id = article.get("data-adid") or article.get("id")
            title_elem = article.select_one("a.ellipsis, h2 a, .aditem-main--title a")
            price_elem = article.select_one(".aditem-main--middle--price-shipping--price, [class*='price']")
            location_elem = article.select_one(".aditem-main--top--left, [class*='location']")
            date_elem = article.select_one(".aditem-main--top--right, [class*='date']")
            desc_elem = article.select_one(".aditem-main--middle--description, [class*='description']")
            img_elem = article.find("img")

            title = title_elem.text.strip() if title_elem else "N/A"
            price_str = price_elem.text.strip() if price_elem else "N/A"
            price_num = parse_numeric_price(price_str)
            
            if not ad_id and title_elem and title_elem.get("href"):
                ad_id = urlparse(title_elem.get("href")).path.split("/")[-1]

            if title != "N/A" and price_str != "N/A" and ad_id:
                link = "https://www.kleinanzeigen.de" + title_elem.get("href") if title_elem.get("href", "").startswith("/") else title_elem.get("href", "")
                
                listings.append({
                    "id": str(ad_id),
                    "platform": "kleinanzeigen",
                    "title": title,
                    "price": price_str,
                    "price_numeric": price_num if price_num is not None else "",
                    "location": location_elem.text.strip().replace("\n", " ") if location_elem else "",
                    "date_posted": date_elem.text.strip().replace("\n", " ") if date_elem else "",
                    "description": desc_elem.text.strip().replace("\n", " ") if desc_elem else "",
                    "link": link,
                    "image_url": img_elem.get("src") or img_elem.get("data-imgsrc", "") if img_elem else "",
                    "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
                })

        next_page = soup.find("a", class_="pagination-next")
        if next_page and next_page.get("href"):
            current_url = "https://www.kleinanzeigen.de" + next_page.get("href")
        else:
            current_url = None
            
    return listings

def scrape_generic_platform(driver, url, platform):
    print(f"   [{platform}] Scraping: {url}")
    driver.get(url)
    time.sleep(5)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    
    listings = []
    # Generic article/card search across mobile.de / autoscout24
    cards = soup.select("article, [class*='list-item'], [class*='result-item'], .list-entry")
    
    for idx, card in enumerate(cards[:25]):
        title_elem = card.select_one("h2, h3, a[class*='title'], [class*='title']")
        price_elem = card.select_one("[class*='price'], [data-testid*='price']")
        link_elem = card.find("a", href=True)
        
        if title_elem and price_elem:
            title = title_elem.text.strip()
            price_str = price_elem.text.strip()
            link = link_elem["href"] if link_elem else url
            if link.startswith("/"):
                link = f"https://{urlparse(url).netloc}{link}"
            
            item_id = card.get("id") or card.get("data-id") or str(abs(hash(link)))
            
            listings.append({
                "id": item_id,
                "platform": platform,
                "title": title,
                "price": price_str,
                "price_numeric": parse_numeric_price(price_str) or "",
                "location": "",
                "date_posted": "",
                "description": "",
                "link": link,
                "image_url": "",
                "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
            })
            
    return listings

def send_email_alert(new_cars):
    if not SMTP_USER or not SMTP_PASS or not ALERT_EMAIL:
        print("SMTP secrets missing. Skipping email alert.")
        return

    recipients = [ALERT_EMAIL]
    if ALERT_EMAIL2:
        recipients.append(ALERT_EMAIL2)

    subject = f"🚗 {len(new_cars)} New Multi-Platform Deal(s) Found!"
    
    body = f"Hallo,\n\n{len(new_cars)} new car listing(s) matching your saved searches were found:\n\n"
    for car in new_cars:
        body += f"• [{car['platform'].upper()}] {car['title']}\n"
        body += f"  Price: {car['price']}\n"
        body += f"  Location: {car['location']}\n"
        body += f"  Link: {car['link']}\n\n"
    body += "(Automated alert from Multi-Platform Car Scraper)\n"

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"Alert email sent to {recipients}!")
    except Exception as e:
        print(f"Failed to send email: {e}")

def main():
    target_urls = load_target_urls()
    print(f"Loaded {len(target_urls)} search URL(s) from {URLS_FILE} / configuration.")

    if not os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    fieldnames = ["id", "platform", "title", "price", "price_numeric", "location", "date_posted", "description", "link", "image_url", "scraped_at"]

    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        try:
            seen_ids = set(json.load(f))
        except Exception:
            seen_ids = set()

    driver = get_driver()
    all_scraped_listings = []
    new_alerts = []

    try:
        for idx, url in enumerate(target_urls, 1):
            platform = detect_platform(url)
            print(f"\n--- Processing Target {idx}/{len(target_urls)} [{platform}]: {url} ---")
            
            if platform == "kleinanzeigen":
                scraped = scrape_kleinanzeigen(driver, url)
            else:
                scraped = scrape_generic_platform(driver, url, platform)
                
            print(f"Extracted {len(scraped)} listing(s) from {platform}.")
            all_scraped_listings.extend(scraped)

            for car in scraped:
                if car["id"] not in seen_ids:
                    new_alerts.append(car)
                    seen_ids.add(car["id"])

    finally:
        driver.quit()

    print(f"\nTotal listings scraped across all URLs: {len(all_scraped_listings)}")
    print(f"New deal alerts to trigger: {len(new_alerts)}")

    if all_scraped_listings:
        # Append all scraped listings to CSV
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writerows(all_scraped_listings)

    # Save updated cache
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_ids), f, indent=2)

    if new_alerts:
        send_email_alert(new_alerts)

if __name__ == "__main__":
    main()
