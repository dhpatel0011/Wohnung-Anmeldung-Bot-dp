import os
import json
import csv
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Secrets loaded from environment variables
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL")
ALERT_EMAIL2 = os.environ.get("ALERT_EMAIL2", "")

DEFAULT_SEARCH_URL = "https://www.kleinanzeigen.de/s-autos/muenchen/sortierung:neuste/anzeige:angebote/preis::7000/c216l6411r30+autos.km_i:%2C100000+autos.schaden_s:nein+autos.tuevy_i:2028+autos.umweltplakette_s:4_gruen"
env_url = os.environ.get("SEARCH_URL", "")
SEARCH_URL = env_url.strip() if env_url and env_url.strip() else DEFAULT_SEARCH_URL

MAX_PAGES = int(os.environ.get("MAX_PAGES", "3"))

CACHE_FILE = "seen_cars.json"
CSV_FILE = "results.csv"

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
    clean_str = price_str.replace(".", "")
    match = re.search(r"(\d+)", clean_str)
    if match:
        return int(match.group(1))
    return None

def extract_article_data(article):
    """Extract listing attributes with robust fallback selectors."""
    ad_id = article.get("data-adid") or article.get("id")
    
    # Title & Link
    title_elem = (
        article.find("a", class_="ellipsis")
        or article.select_one("h2 a")
        or article.select_one("a[href*='/s-anzeige/']")
    )
    
    # Price
    price_elem = (
        article.find("p", class_=re.compile("price", re.I))
        or article.select_one("[class*='price']")
    )
    
    # Location
    location_elem = (
        article.find("div", class_=re.compile("top--left", re.I))
        or article.select_one("[class*='location']")
        or article.select_one("[class*='top--left']")
    )
    
    # Date posted
    date_elem = (
        article.find("div", class_=re.compile("top--right", re.I))
        or article.select_one("[class*='date']")
        or article.select_one("[class*='top--right']")
    )
    
    # Description
    desc_elem = (
        article.find("p", class_=re.compile("description", re.I))
        or article.select_one("[class*='description']")
    )
    
    # Image
    img_elem = article.find("img")

    title = title_elem.text.strip() if title_elem else "N/A"
    link = ("https://www.kleinanzeigen.de" + title_elem.get("href")) if title_elem and title_elem.get("href") else ""
    
    price_str = price_elem.text.strip() if price_elem else ""
    if not price_str:
        # Fallback: search text inside article for price pattern
        price_match = re.search(r"\d+[\d\.]*\s*€(?:\s*VB)?", article.text)
        if price_match:
            price_str = price_match.group(0)

    location = location_elem.text.strip().replace("\n", " ") if location_elem else ""
    date_posted = date_elem.text.strip().replace("\n", " ") if date_elem else ""
    description = desc_elem.text.strip().replace("\n", " ") if desc_elem else ""
    
    image_url = ""
    if img_elem:
        image_url = img_elem.get("src") or img_elem.get("data-imgsrc") or img_elem.get("data-src") or ""

    if not ad_id:
        if link:
            ad_id = link.split("/")[-1].split("-")[0]
        else:
            ad_id = str(hash(title + price_str))

    return {
        "id": str(ad_id),
        "title": title,
        "price": price_str,
        "price_numeric": parse_numeric_price(price_str) or "",
        "location": location,
        "date_posted": date_posted,
        "description": description,
        "link": link,
        "image_url": image_url,
        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

def send_email_alert(new_cars):
    if not SMTP_USER or not SMTP_PASS or not ALERT_EMAIL:
        print("SMTP secrets missing or incomplete. Skipping email notification.")
        return

    recipients = [ALERT_EMAIL]
    if ALERT_EMAIL2:
        recipients.append(ALERT_EMAIL2)

    subject = f"🚗 {len(new_cars)} New Filtered Car Deal(s) Found on Kleinanzeigen!"
    
    body = f"Hallo,\n\n{len(new_cars)} new car listing(s) matching your exact filters were found:\n\n"
    for car in new_cars:
        body += f"• {car['title']}\n"
        body += f"  Price: {car['price']}\n"
        body += f"  Location: {car['location']}\n"
        body += f"  Date: {car['date_posted']}\n"
        if car['description']:
            body += f"  Description: {car['description'][:120]}...\n"
        body += f"  Link: {car['link']}\n\n"
    body += "(Automated alert from Kleinanzeigen Car Bot - Raw Extractor)\n"

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"Alert email successfully sent to {recipients}!")
    except Exception as e:
        print(f"Failed to send email alert: {e}")

def main():
    print("Starting Selenium Car Scraper (v6 Raw Extractor)...")
    print(f"Target URL: {SEARCH_URL}")

    # Load seen IDs cache
    seen_ids = set()
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, list):
                    seen_ids = set(content)
        except Exception as e:
            print(f"Reading cache file failed: {e}")

    driver = get_driver()
    all_scraped_cars = []
    new_cars_for_alert = []
    current_url = SEARCH_URL
    page_count = 0

    try:
        while current_url and page_count < MAX_PAGES:
            page_count += 1
            print(f"\n--- Scraping Page {page_count} of max {MAX_PAGES} ---")
            print(f"Loading: {current_url}")
            
            driver.get(current_url)
            time.sleep(4)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            articles = soup.find_all("article", class_="aditem")
            if not articles:
                articles = soup.select("article[data-adid]")
            if not articles:
                articles = soup.select(".ad-listitem, .aditem")
            
            print(f"Found {len(articles)} listing element(s) on page {page_count}.")

            for article in articles:
                car_data = extract_article_data(article)
                if not car_data["id"] or car_data["title"] == "N/A":
                    continue

                all_scraped_cars.append(car_data)

                if car_data["id"] not in seen_ids:
                    new_cars_for_alert.append(car_data)
                    seen_ids.add(car_data["id"])

            # Check next page link
            next_page = soup.find("a", class_="pagination-next")
            if next_page and next_page.get("href"):
                current_url = "https://www.kleinanzeigen.de" + next_page.get("href")
            else:
                current_url = None

    finally:
        driver.quit()

    print(f"\nTotal raw listings extracted: {len(all_scraped_cars)}")
    print(f"Total NEW listings for alert: {len(new_cars_for_alert)}")

    # ALWAYS write all extracted listings to results.csv for notebook analysis
    fieldnames = [
        "id", "title", "price", "price_numeric", "location", 
        "date_posted", "description", "link", "image_url", "scraped_at"
    ]

    existing_rows = {}
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "id" in row and row["id"]:
                        existing_rows[row["id"]] = row
        except Exception as e:
            print(f"Reading existing CSV failed: {e}")

    # Merge newly scraped listings into dictionary
    for car in all_scraped_cars:
        existing_rows[car["id"]] = car

    # Write merged dataset to results.csv
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows.values())

    print(f"Saved {len(existing_rows)} total cumulative listings into {CSV_FILE}.")

    # Save updated seen_cars.json
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_ids), f, indent=2)

    # Send email notification if there are NEW cars
    if new_cars_for_alert:
        send_email_alert(new_cars_for_alert)
    else:
        print("No new listings found for alert.")

if __name__ == "__main__":
    main()
