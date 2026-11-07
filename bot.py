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

# 5 слотов публикации в UTC (06:00, 09:30, 13:00, 16:30, 20:00 по Москве = UTC+3)
ALLOWED_UTC_HOURS = {3, 6, 10, 13, 17}

# ИСТОЧНИКИ ПО ТЕМЕ СРО
RSS_FEEDS = [
    "http://tpp-sro.ru/?feed=rss2",            # Новости СРО (пример)
    "https://newsrus.su/rss/news",             # Служба строительных новостей (раздел СРО)
    "https://omorrss.ru/rss/news",              # Российский Союз Строителей
    "https://know-house.ru/novosti/rss.xml",   # Строительные новости (может содержать СРО)
]

# Ключевые слова для фильтрации (чтобы отсечь лишнее и оставить только СРО/строительство)
BLOCKED_KEYWORDS = [
    "сво", "спецоперац", "украин", "україн", "зеленск",
    "zelensky", "zelenskyy", "kiev", "kyiv",
    "донбасс", "донецк", "луганск", "киев",
    "всу", "кремль", "путин", "харьков", "одесс",
    "мариупол", "бахмут", "курск", "белгород",
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
    # Поиск картинки в RSS-ленте
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
    
    # Пытаемся найти картинку на сайте новости
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
    seven_days_ago = now - (7 * 24 * 60 * 60) # 7 дней в секундах
    
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:15]:
                link = getattr(e, "link", "")
                title = getattr(e, "title", "").strip()
                raw_summary = getattr(e, "summary", "")
                summary = clean_html(raw_summary)
                
                # ФИЛЬТР ПО ДАТЕ: новость не старше 7 дней
                published_parsed = getattr(e, "published_parsed", None)
                if published_parsed:
                    # Конвертируем struct_time в timestamp и сравниваем
                    if time.mktime(published_parsed) < seven_days_ago:
                        continue # Пропускаем старую новость
                
                # Проверка на русский язык в заголовке
                if link and title and RUSSIAN_RE.search(title):
                    entries.append({
                        "title": title, 
                        "link": link, 
                        "text": f"{title} {summary}".lower(),
                        "summary": summary,
                        "image_url": extract_image(e)
                    })
        except Exception:
            continue
    return entries

def is_blocked(entry):
    text = entry["text"]
    return any(kw in text for kw in BLOCKED_KEYWORDS)

def post_to_channel(entry):
    summary_text = entry["summary"]
    if len(summary_text) > 500:
        summary_text = summary_text[:500] + "..."
    if not summary_text:
        summary_text = "Подробности в источнике."

    # ФОРМИРУЕМ ПОДПИСЬ: Заголовок + Текст + ССЫЛКА
    caption = f'<b>{entry["title"]}</b>\n\n{summary_text}\n\n<a href="{entry["link"]}">Читать полностью</a>'
    
    # Пытаемся отправить фото
    if entry.get("image_url"):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                json={
                    "chat_id": CHANNEL_ID,
                    "photo": entry["image_url"],
                    "caption": caption[:1024], # Лимит подписи к фото
                    "parse_mode": "HTML",
                },
                timeout=30,
            )
            if resp.ok:
                return True, resp.text
            else:
                print(f"Не удалось отправить фото ({resp.text}). Пробую текст.")
        except Exception as e:
            print(f"Ошибка при отправке фото: {e}")

    # Страховка: отправляем текст, если фото не ушло
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
    entries = [e for e in fetch_entries() if not is_blocked(e)]
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
