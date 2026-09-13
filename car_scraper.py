import os
import json
import csv
import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Secrets loaded from environment variables
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL")
ALERT_EMAIL2 = os.environ.get("ALERT_EMAIL2", "")

# Search parameters (Replace with your exact Kleinanzeigen search URL)
SEARCH_URL = "https://www.kleinanzeigen.de/s-autos/muenchen/sortierung:neuste/anzeige:angebote/preis::7000/c216l6411r30+autos.km_i:%2C100000+autos.schaden_s:nein+autos.tuevy_i:2028+autos.umweltplakette_s:4_gruen"
CACHE_FILE = "seen_cars.json"
CSV_FILE = "results.csv"

def send_email_alert(new_cars):
    if not SMTP_USER or not SMTP_PASS or not ALERT_EMAIL:
        print("SMTP secrets missing. Skipping email notification.")
        return

    recipients = [ALERT_EMAIL]
    if ALERT_EMAIL2:
        recipients.append(ALERT_EMAIL2)

    subject = f"🚗 {len(new_cars)} New Car Deal(s) Found on Kleinanzeigen!"
    
    body = "Hallo,\n\nHere are the latest car listings matching your search:\n\n"
    for car in new_cars:
        body += f"• {car['title']}\n  Price: {car['price']}\n  Location: {car['location']}\n  Link: {car['link']}\n\n"
    body += "(This is an automated alert from your Kleinanzeigen Car Bot)\n"

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
    # Load previously seen listing IDs
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            seen_ids = set(json.load(f))
    else:
        seen_ids = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    print(f"Fetching listings from: {SEARCH_URL}")
    response = requests.get(SEARCH_URL, headers=headers)
    
    if response.status_code != 200:
        print(f"Error loading page: Status code {response.status_code}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    articles = soup.find_all("article", class_="aditem")
    
    new_cars = []
    
    for article in articles:
        ad_id = article.get("data-adid")
        if not ad_id or ad_id in seen_ids:
            continue

        title_elem = article.find("a", class_="ellipsis")
        price_elem = article.find("p", class_="aditem-main--middle--price-shipping--price")
        location_elem = article.find("div", class_="aditem-main--top--left")

        if title_elem and price_elem:
            title = title_elem.text.strip()
            price = price_elem.text.strip()
            location = location_elem.text.strip().replace("\n", " ") if location_elem else "N/A"
            link = "https://www.kleinanzeigen.de" + title_elem.get("href")

            car_data = {
                "id": ad_id,
                "title": title,
                "price": price,
                "location": location,
                "link": link
            }
            new_cars.append(car_data)
            seen_ids.add(ad_id)

    print(f"Found {len(new_cars)} new car listing(s).")

    if new_cars:
        # 1. Update JSON cache
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen_ids), f, indent=2)

        # 2. Append to CSV file for Gemini Notebook
        file_exists = os.path.exists(CSV_FILE)
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "title", "price", "location", "link"])
            if not file_exists:
                writer.writeheader()
            writer.writerows(new_cars)

        # 3. Send Email Alert
        send_email_alert(new_cars)

if __name__ == "__main__":
    main()
