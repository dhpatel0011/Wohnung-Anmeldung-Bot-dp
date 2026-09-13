import os
import json
import csv
import re
import time
from curl_cffi import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Secrets loaded from environment variables
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL")
ALERT_EMAIL2 = os.environ.get("ALERT_EMAIL2", "")

# Search parameters - Can be overridden via environment variable SEARCH_URL
DEFAULT_SEARCH_URL = "https://www.kleinanzeigen.de/s-autos/muenchen/sortierung:neuste/anzeige:angebote/preis::7000/c216l6411r30+autos.km_i:%2C100000+autos.schaden_s:nein+autos.tuevy_i:2028+autos.umweltplakette_s:4_gruen"
SEARCH_URL = os.environ.get("SEARCH_URL", DEFAULT_SEARCH_URL)

# How many pages of search results to scrape (default: 3 pages)
MAX_PAGES = int(os.environ.get("MAX_PAGES", "3"))

CACHE_FILE = "seen_cars.json"
CSV_FILE = "results.csv"

def parse_numeric_price(price_str):
    """Extract numeric integer price from German price string (e.g., '6.990 € VB' -> 6990)."""
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
    body += "(Automated alert from Kleinanzeigen Car Bot - Filtered Extraction)\n"

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

def scrape_page(url, headers):
    print(f"Fetching URL: {url}")
    try:
        response = requests.get(url, headers=headers, impersonate="chrome120", timeout=15)
        if response.status_code == 200:
            return BeautifulSoup(response.text, "html.parser")
        else:
            print(f"Failed to load page. HTTP Status: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching page: {e}")
        return None

def main():
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

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }

    new_cars = []
    current_url = SEARCH_URL
    page_count = 0

    while current_url and page_count < MAX_PAGES:
        page_count += 1
        print(f"\n--- Scraping Page {page_count} of max {MAX_PAGES} ---")
        soup = scrape_page(current_url, headers)
        if not soup:
            break

        articles = soup.find_all("article", class_="aditem")
        print(f"Found {len(articles)} listings on page {page_count}.")

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

        # Check for Next Page link
        next_page_elem = soup.find("a", class_="pagination-next")
        if next_page_elem and next_page_elem.get("href"):
            current_url = "https://www.kleinanzeigen.de" + next_page_elem.get("href")
            time.sleep(2)
        else:
            print("No next page link found. Reached end of search results.")
            break

    print(f"\nTotal new listings extracted: {len(new_cars)}")

    if new_cars:
        # Save updated seen cache
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen_ids), f, indent=2)

        # Append structured data to CSV for Gemini Notebook
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "title", "price", "price_numeric", "location", "date_posted", "description", "link", "image_url"
            ])
            writer.writerows(new_cars)

        print(f"Appended {len(new_cars)} listings to {CSV_FILE}.")

        # Send alert notification
        send_email_alert(new_cars)

if __name__ == "__main__":
    main()
