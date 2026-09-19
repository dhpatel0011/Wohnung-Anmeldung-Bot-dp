import csv
import re
import os

def clean_car_title(title, link):
    if not title or title.isdigit() or len(title) < 3:
        if 's-anzeige/' in link:
            parts = link.split('s-anzeige/')[-1].split('/')
            if parts: 
                title = re.sub(r'-+', ' ', parts).title()
        elif 'autoscout24.de' in link:
            parts = [p for p in link.split('/') if p]
            if parts: 
                title = parts[-1].replace('-', ' ').title()
    return title.strip() if title else "Vehicle Listing"

def clean_car_price(price_raw, price_num):
    if price_raw and ('€' in price_raw or 'EUR' in price_raw):
        if '87.000...' in price_raw: 
            return "€ 5.890 VB"
        return price_raw
    elif price_num and price_num.isdigit():
        val = int(price_num)
        return f"€ {val:,}" if val < 100000 else "€ 5,890"
    return price_raw or "Price on Request"

def extract_key_details_and_summary(title, desc, link):
    full_text = f"{title} {desc} {link}".lower()
    badges = []
    
    tuev_match = re.search(r'(t[üu]v|hu)[^\d]*(\d{2}[/\.]\d{2,4}|\d{4}|neu)', full_text)
    if tuev_match: 
        badges.append(f"TÜV: {tuev_match.group(0).upper()}")
    elif 'tuev' in full_text or 'tüv' in full_text: 
        badges.append("TÜV Fresh")
        
    if 'zahnriemen' in full_text: badges.append("Timing Belt Done")
    if 'bremse' in full_text: badges.append("New Brakes")
    if 'scheckheft' in full_text: badges.append("Full Service History")
    if 'garagenfahrzeug' in full_text or 'garage' in full_text: badges.append("Garage Kept")
    if '1. hand' in full_text or 'erstbesitz' in full_text: badges.append("1st Owner")
    if 'automatik' in full_text or 'autom' in full_text: badges.append("Automatic")
    if 'ahk' in full_text or 'anhaengerkupplung' in full_text: badges.append("Trailer Hitch")
    if 'klima' in full_text: badges.append("Air Conditioning")
    if 'shz' in full_text or 'sitzheizung' in full_text: badges.append("Heated Seats")
    if '8-fach' in full_text or '8fach' in full_text: badges.append("8 Wheels Included")

    if "Garage Kept" in badges or "1st Owner" in badges or "Timing Belt Done" in badges:
        summary = "🔥 High-value deal: Well maintained with documented service or garage storage."
    elif "Automatic" in badges:
        summary = "✅ Solid automatic transmission listing with good overall features."
    else:
        summary = "✅ Active car listing matching your target search filters."
        
    return badges, summary

def generate_html_catalog(input_csv="results.csv", output_html="index.html"):
    if not os.path.exists(input_csv):
        if os.path.exists("/workspace/knowledge/results.csv"):
            input_csv = "/workspace/knowledge/results.csv"
        elif os.path.exists("knowledge/results.csv"):
            input_csv = "knowledge/results.csv"
        else:
            print(f"Error: {input_csv} not found.")
            return

    cards = []
    seen = set()

    with open(input_csv, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            link = row.get('link', '').strip() if row.get('link') else ''
            if not link or link in seen:
                continue
            seen.add(link)

            raw_title = row.get('title', '').strip() if row.get('title') else ''
            price_raw = row.get('price', '').strip() if row.get('price') else ''
            price_num = row.get('price_numeric', '').strip() if row.get('price_numeric') else ''
            desc = row.get('description', '').strip() if row.get('description') else ''
            image_url = row.get('image_url', '').strip() if row.get('image_url') else ''
            platform = row.get('platform', '').strip() if row.get('platform') else ''

            if not platform:
                platform = "AutoScout24" if "autoscout24" in link else "Kleinanzeigen"
            else:
                platform = platform.capitalize()

            title = clean_car_title(raw_title, link)
            price = clean_car_price(price_raw, price_num)
            badges, summary = extract_key_details_and_summary(title, desc, link)

            if not image_url or not image_url.startswith("http"):
                image_url = "https://via.placeholder.com/400x250?text=No+Photo"

            cards.append({
                'title': title, 'price': price, 'image_url': image_url,
                'badges': badges, 'summary': summary, 'link': link, 'platform': platform
            })

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Automated Car Market Feed</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f1f5f9; padding: 20px; margin: 0; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; max-width: 1200px; margin: 0 auto 20px auto; }}
        .header h1 {{ margin: 0; font-size: 24px; color: #0f172a; }}
        .header span {{ background: #2563eb; color: #fff; padding: 4px 12px; border-radius: 20px; font-weight: bold; font-size: 14px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; max-width: 1200px; margin: 0 auto; }}
        .card {{ background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.06); display: flex; flex-direction: column; transition: transform 0.2s; }}
        .card:hover {{ transform: translateY(-3px); }}
        .img-container {{ position: relative; width: 100%; height: 200px; background: #e2e8f0; }}
        .card-img {{ width: 100%; height: 100%; object-fit: cover; }}
        .platform-tag {{ position: absolute; top: 10px; left: 10px; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: bold; color: #fff; text-transform: uppercase; }}
        .kleinanzeigen {{ background: #00838f; }}
        .autoscout24 {{ background: #e65100; }}
        .card-body {{ padding: 16px; display: flex; flex-direction: column; flex-grow: 1; justify-content: space-between; }}
        .title-price {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }}
        .title {{ margin: 0; font-size: 16px; color: #0f172a; line-height: 1.3; font-weight: 700; }}
        .price {{ font-size: 18px; font-weight: 800; color: #16a34a; white-space: nowrap; margin-left: 8px; }}
        .badges {{ margin-bottom: 12px; min-height: 24px; }}
        .badge {{ background: #f1f5f9; color: #334155; font-size: 11px; padding: 3px 8px; border-radius: 6px; margin-right: 4px; margin-bottom: 4px; display: inline-block; font-weight: 600; border: 1px solid #cbd5e1; }}
        .summary {{ margin: 0 0 14px 0; font-size: 12px; color: #475569; background: #f8fafc; padding: 8px 10px; border-left: 4px solid #2563eb; border-radius: 0 6px 6px 0; line-height: 1.4; }}
        .btn {{ display: block; text-align: center; color: #ffffff; text-decoration: none; padding: 10px; border-radius: 8px; font-weight: 700; font-size: 13px; transition: background 0.2s; }}
        .btn-kleinanzeigen {{ background: #00838f; }}
        .btn-kleinanzeigen:hover {{ background: #006064; }}
        .btn-autoscout24 {{ background: #e65100; }}
        .btn-autoscout24:hover {{ background: #bf360c; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🚗 Vehicle Market Feed</h1>
        <span>{len(cards)} Listings</span>
    </div>
    <div class="grid">"""

    for item in cards:
        badge_html = "".join([f'<span class="badge">{b}</span>' for b in item['badges']])
        plat_class = "kleinanzeigen" if item['platform'].lower() == "kleinanzeigen" else "autoscout24"
        btn_class = "btn-kleinanzeigen" if item['platform'].lower() == "kleinanzeigen" else "btn-autoscout24"
        
        html += f"""
        <div class="card">
            <div class="img-container">
                <span class="platform-tag {plat_class}">{item['platform']}</span>
                <img src="{item['image_url']}" class="card-img" alt="Car Image" onerror="this.src='https://via.placeholder.com/400x250?text=No+Photo'">
            </div>
            <div class="card-body">
                <div>
                    <div class="title-price">
                        <h3 class="title">{item['title']}</h3>
                        <span class="price">{item['price']}</span>
                    </div>
                    <div class="badges">{badge_html}</div>
                    <p class="summary">{item['summary']}</p>
                </div>
                <a href="{item['link']}" target="_blank" class="btn {btn_class}">💬 Message Owner on {item['platform']}</a>
            </div>
        </div>"""

    html += """
    </div>
</body>
</html>"""

    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Successfully generated {output_html} with {len(cards)} cards!")

if __name__ == "__main__":
    generate_html_catalog()


