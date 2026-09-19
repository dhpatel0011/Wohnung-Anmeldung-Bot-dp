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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Secrets loaded from environment variables
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL")
ALERT_EMAIL2 = os.environ.get("ALERT_EMAIL2", "")

MAX_PAGES = int(os.environ.get("MAX_PAGES", "2"))
CACHE_FILE = "seen_cars.json"
CSV_FILE = "results.csv"
URLS_FILE = "urls.txt"

DEFAULT_URLS = [
    "https://www.kleinanzeigen.de/s-autos/88250/sortierung:empfohlen/preis::3500/c216l15340r100+autos.ez_i:2005%2C+autos.km_i:%2C150000+autos.tuevy_i:2027%2C"
]

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
        val = int(match.group(1))
        if val > 1000000:  # handle mileage concatenated strings
            sub_match = re.findall(r"\d{3,5}", clean_str)
            if sub_match:
                return int(sub_match[-1])
        return val
    return None

def load_urls():
    if os.path.exists(URLS_FILE):
        urls = []
        with open(URLS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
        if urls:
            return urls
    return DEFAULT_URLS

def dismiss_cookie_banners(driver):
    """Attempt to click accept on GDPR/Cookie banners if present."""
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

def scrape_kleinanzeigen(driver, url, max_pages, seen_ids):
    listings = []
    current_url = url
    page_count = 0

    while current_url and page_count < max_pages:
        page_count += 1
        print(f"   [Kleinanzeigen] Page {page_count}: {current_url}")
        driver.get(current_url)
        time.sleep(4)
        dismiss_cookie_banners(driver)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        articles = soup.find_all("article", class_="aditem")
        if not articles:
            articles = soup.select("article[data-adid]")
        if not articles:
            articles = soup.select(".ad-listitem")

        print(f"   Found {len(articles)} listing element(s).")

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
            location_elem = article.find("div", class_="aditem-main--top--left") or article.select_one("[class*='location']")
            date_elem = article.find("div", class_="aditem-main--top--right") or article.select_one("[class*='date']")
            desc_elem = article.find("p", class_="aditem-main--middle--description") or article.select_one("[class*='description']")
            img_elem = article.find("img")

            title = title_elem.text.strip() if title_elem else "Unclassified Deal"
            price_str = price_elem.text.strip() if price_elem else "N/A"
            price_num = parse_numeric_price(price_str)
            location = location_elem.text.strip().replace("\n", " ") if location_elem else ""
            date_posted = date_elem.text.strip().replace("\n", " ") if date_elem else ""
            description = desc_elem.text.strip().replace("\n", " ") if desc_elem else ""
            
            href = title_elem.get("href") if title_elem and title_elem.get("href") else ""
            link = "https://www.kleinanzeigen.de" + href if href.startswith("/") else href
            image_url = img_elem.get("src") or img_elem.get("data-imgsrc", "") if img_elem else ""

            item = {
                "id": ad_id,
                "platform": "kleinanzeigen",
                "title": title,
                "price": price_str,
                "price_numeric": price_num if price_num is not None else "",
                "location": location,
                "date_posted": date_posted,
                "description": description,
                "link": link,
                "image_url": image_url,
                "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "_is_new": is_new
            }
            listings.append(item)
            seen_ids.add(ad_id)

        next_page = soup.find("a", class_="pagination-next")
        if next_page and next_page.get("href"):
            current_url = "https://www.kleinanzeigen.de" + next_page.get("href")
        else:
            current_url = None

    return listings

def scrape_autoscout24(driver, url, max_pages, seen_ids):
    listings = []
    print(f"   [AutoScout24] Scraping: {url}")
    driver.get(url)
    time.sleep(5)
    dismiss_cookie_banners(driver)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    articles = soup.select("article, [data-testid='list-item']")

    for article in articles:
        link_elem = article.find("a", href=True)
        if not link_elem:
            continue
        
        href = link_elem["href"]
        ad_id_match = re.search(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", href)
        ad_id = ad_id_match.group(1) if ad_id_match else href.split("/")[-1]

        is_new = ad_id not in seen_ids

        title_elem = article.select_one("h2") or article.find("a")
        price_elem = article.select_one("[class*='Price'], [class*='price']")
        
        title = title_elem.text.strip() if title_elem else "AutoScout24 Deal"
        price_str = price_elem.text.strip() if price_elem else "N/A"
        price_num = parse_numeric_price(price_str)
        link = "https://www.autoscout24.de" + href if href.startswith("/") else href

        item = {
            "id": ad_id,
            "platform": "autoscout24",
            "title": title,
            "price": price_str,
            "price_numeric": price_num if price_num is not None else "",
            "location": "",
            "date_posted": "",
            "description": "",
            "link": link,
            "image_url": "",
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "_is_new": is_new
        }
        listings.append(item)
        seen_ids.add(ad_id)

    return listings

def send_email_alert(new_cars):
    if not SMTP_USER or not SMTP_PASS or not ALERT_EMAIL:
        print("SMTP credentials missing. Skipping alert email.")
        return

    recipients = [ALERT_EMAIL]
    if ALERT_EMAIL2:
        recipients.append(ALERT_EMAIL2)

    subject = f"🚗 {len(new_cars)} New Car Deal(s) Found Across Platforms!"
    body = f"Hallo,\n\n{len(new_cars)} new vehicle listing(s) match your multi-platform search:\n\n"
    for car in new_cars:
        body += f"• [{car['platform'].upper()}] {car['title']}\n"
        body += f"  Price: {car['price']}\n"
        if car['location']:
            body += f"  Location: {car['location']}\n"
        body += f"  Link: {car['link']}\n\n"
    body += "(Automated alert from Multi-Platform Vehicle Bot)\n"

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
    print("Starting Multi-Platform Car Scraper...")

    # Ensure files exist
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

    urls = load_urls()
    print(f"Loaded {len(urls)} search URL(s) from {URLS_FILE} / configuration.")

    driver = get_driver()
    all_extracted = []
    new_alerts = []

    try:
        for idx, url in enumerate(urls, 1):
            print(f"\n--- Processing Target {idx}/{len(urls)}: {url} ---")
            if "kleinanzeigen.de" in url:
                extracted = scrape_kleinanzeigen(driver, url, MAX_PAGES, seen_ids)
            elif "autoscout24" in url:
                extracted = scrape_autoscout24(driver, url, MAX_PAGES, seen_ids)
            else:
                print(f"Unsupported platform URL: {url}")
                continue

            print(f"Extracted {len(extracted)} listing(s).")
            for item in extracted:
                if item.get("_is_new"):
                    new_alerts.append(item)
                all_extracted.append(item)

    finally:
        driver.quit()

    print(f"\nTotal listings scraped across all URLs: {len(all_extracted)}")
    print(f"New deal alerts to trigger: {len(new_alerts)}")

    # Always update CSV with scraped data
    if all_extracted:
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writerows(all_extracted)

    # Save cache
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_ids), f, indent=2)

    # Send alerts if new
    if new_alerts:
        send_email_alert(new_alerts)

if __name__ == "__main__":
    main()
