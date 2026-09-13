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

# Secrets loaded from environment variables
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL")
ALERT_EMAIL2 = os.environ.get("ALERT_EMAIL2", "")

DEFAULT_SEARCH_URL = "https://www.kleinanzeigen.de/s-autos/muenchen/sortierung:neuste/anzeige:angebote/preis::7000/c216l6411r50+autos.schaden_s:nein+autos.schadstoffklasse_s:euro4+autos.tuevy_i:2028%2C"
env_url = os.environ.get("SEARCH_URL", "")
SEARCH_URL = env_url.strip() if env_url and env_url.strip() else DEFAULT_SEARCH_URL

MAX_PAGES = int(os.environ.get("MAX_PAGES", "2"))

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
    body += "(Automated alert from Kleinanzeigen Car Bot - Selenium Edition)\n"

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
    print(f"Starting Selenium Car Scraper...")
    print(f"Target URL: {SEARCH_URL}")

    # Guarantee cache and CSV file existence upfront
    if not os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "title", "price", "price_numeric", "location", "date_posted", "description", "link", "image_url"
            ])
            writer.writeheader()

    # Load seen IDs
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        try:
            seen_ids = set(json.load(f))
        except Exception:
            seen_ids = set()

    driver = get_driver()
    new_cars = []
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
            
            print(f"Found {len(articles)} listing element(s) on page {page_count}.")

            for article in articles:
                ad_id = article.get("data-adid")
                if not ad_id or ad_id in seen_ids:
                    continue

                title_elem = article.find("a", class_="ellipsis")
                price_elem = article.find("p", class_="aditem-main--middle--price-shipping--price")
                location_elem = article.find("div", class_="aditem-main--top--left")
                date_elem = article.find("div", class_="aditem-main--top--right")
                desc_elem = article.find("p", class_="aditem-main--middle--description")
                img_elem = article.find("img")

                if title_elem and price_elem:
                    title = title_elem.text.strip()
                    price_str = price_elem.text.strip()
                    price_num = parse_numeric_price(price_str)
                    location = location_elem.text.strip().replace("\n", " ") if location_elem else ""
                    date_posted = date_elem.text.strip().replace("\n", " ") if date_elem else ""
                    description = desc_elem.text.strip().replace("\n", " ") if desc_elem else ""
                    link = "https://www.kleinanzeigen.de" + title_elem.get("href")
                    image_url = img_elem.get("src") or img_elem.get("data-imgsrc", "") if img_elem else ""

                    car_data = {
                        "id": ad_id,
                        "title": title,
                        "price": price_str,
                        "price_numeric": price_num if price_num is not None else "",
                        "location": location,
                        "date_posted": date_posted,
                        "description": description,
                        "link": link,
                        "image_url": image_url
                    }
                    new_cars.append(car_data)
                    seen_ids.add(ad_id)

            # Check next page link
            next_page = soup.find("a", class_="pagination-next")
            if next_page and next_page.get("href"):
                current_url = "https://www.kleinanzeigen.de" + next_page.get("href")
            else:
                current_url = None

    finally:
        driver.quit()

    print(f"\nTotal new listings extracted: {len(new_cars)}")

    if new_cars:
        # Update JSON cache
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen_ids), f, indent=2)

        # Append to CSV
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "title", "price", "price_numeric", "location", "date_posted", "description", "link", "image_url"
            ])
            writer.writerows(new_cars)

        # Send Email Alert
        send_email_alert(new_cars)

if __name__ == "__main__":
    main()
