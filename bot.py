import os
import random
import sys
import datetime
import re
import time
import feedparser
import requests
from html import unescape

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

POSTED_FILE = "posted.txt"

ALLOWED_UTC_HOURS = {3, 6, 10, 13, 17}

# ОБНОВЛЕННЫЕ ИСТОЧНИКИ (СРО + аналитика + "инсайды")
RSS_FEEDS = [
    # Основные источники по СРО
    "http://tpp-sro.ru/?feed=rss2",            # Новости СРО (НОСТРОЙ, рейтингование)
    "https://newsrus.su/rss/news",             # Строительные новости (СРО)
    "https://omorrss.ru/rss/news",             # Российский Союз Строителей
    
    # Аналитика и "околоинсайдерские" разборы
    "https://stroygaz.ru/rss/",                # Строительная газета (официально, но часто с "инсайдами" реформ)
    "https://srogazeta.ru/rss/",               # СтройСаморегулирование (разборы 309-ФЗ)
    "https://pravdaosro.ru/feed/",             # "Правда о СРО" (критика, скандалы, разоблачения)
    
    # Строительные новости (для контекста)
    "https://know-house.ru/novosti/rss.xml",
]

# Ключевые слова для фильтрации (оставляем только СРО и строительство)
BLOCKED_KEYWORDS = [
    "сво", "спецоперац", "украин", "україн", "зеленск",
    "zelensky", "zelenskyy", "kiev", "kyiv",
    "донбасс", "донецк", "луганск", "киев",
    "всу", "кремль", "путин", "харьков", "одесс",
    "мариупол", "бахмут", "курск", "белгород",
]

# Слова, которые ДОЛЖНЫ быть в новости (чтобы отсечь нерелевантное)
REQUIRED_KEYWORDS = [
    "сро", "саморегул", "нострой", "ноприз", "строительн", 
    "подрядчик", "компенсационн", "реестр", "допуск"
]

RUSSIAN_RE = re.compile('[а-яА-ЯёЁ]')
TAGS_RE = re.compile(r'<[^>]+>')

def clean_html(raw_html):
    if not raw_html:
        return ""
    clean_text = unescape(TAGS_RE.sub('', raw_html))
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

def extract_image(entry):
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            if media.get('url'): return media.get('url')
    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        return entry.media_thumbnail[0].get('url')
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if 'image' in enc.get('type', ''): return enc.get('href')
    
    raw_summary = getattr(entry, "summary", "")
    if raw_summary:
        img_match = re.search(r'<img[^>]+src="([^">]+)"', raw_summary)
        if img_match: return img_match.group(1)
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(entry["link"], headers=headers, timeout=10)
        if resp.ok:
            og_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', resp.text)
            if og_match: return og_match.group(1)
    except Exception:
        pass
    return None

def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def fetch_entries():
    entries = []
    now = time.time()
    seven_days_ago = now - (7 * 24 * 60 * 60)
    
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:20]: # Берем больше новостей, так как фильтр жесткий
                link = getattr(e, "link", "")
                title = getattr(e, "title", "").strip()
                raw_summary = getattr(e, "summary", "")
                summary = clean_html(raw_summary)
                full_text = f"{title} {summary}".lower()
                
                # Фильтр по дате
                published_parsed = getattr(e, "published_parsed", None)
                if published_parsed:
                    if time.mktime(published_parsed) < seven_days_ago:
                        continue
                
                # Проверка на русский язык
                if not (link and title and RUSSIAN_RE.search(title)):
                    continue
                
                # Проверка на СТОП-слова
                if any(kw in full_text for kw in BLOCKED_KEYWORDS):
                    continue
                
                # Проверка на ОБЯЗАТЕЛЬНЫЕ слова (должна быть тема СРО)
                if not any(kw in full_text for kw in REQUIRED_KEYWORDS):
                    continue
                
                entries.append({
                    "title": title, 
                    "link": link, 
                    "text": full_text,
                    "summary": summary,
                    "image_url": extract_image(e)
                })
        except Exception:
            continue
    return entries

def post_to_channel(entry):
    summary_text = entry["summary"]
    if len(summary_text) > 500:
        summary_text = summary_text[:500] + "..."
    if not summary_text:
        summary_text = "Подробности в источнике."

    caption = f'<b>{entry["title"]}</b>\n\n{summary_text}\n\n<a href="{entry["link"]}">Читать полностью</a>'
    
    if entry.get("image_url"):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                json={
                    "chat_id": CHANNEL_ID,
                    "photo": entry["image_url"],
                    "caption": caption[:1024],
                    "parse_mode": "HTML",
                },
                timeout=30,
            )
            if resp.ok:
                return True, resp.text
        except Exception:
            pass

    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHANNEL_ID,
            "text": caption[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    return resp.ok, resp.text

def main():
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        hour = datetime.datetime.now(datetime.timezone.utc).hour
        if hour not in ALLOWED_UTC_HOURS:
            print(f"Не слот публикации (UTC hour={hour}), выход.")
            return

    posted = load_posted()
    entries = fetch_entries()
    fresh = [e for e in entries if e["link"] not in posted]

    if not fresh:
        print("Нет свежих новостей о СРО за последнюю неделю — выход.")
        return

    entry = random.choice(fresh)
    ok, info = post_to_channel(entry)

    if not ok:
        print(f"Ошибка отправки: {info}")
        sys.exit(1)

    with open(POSTED_FILE, "a", encoding="utf-8") as f:
        f.write(entry["link"] + "\n")
    print(f"Опубликовано: {entry['title']}")

if __name__ == "__main__":
    main()
