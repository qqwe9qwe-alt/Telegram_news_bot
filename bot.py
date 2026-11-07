"""
Бот новостей в Telegram-канал (GitHub Actions, бесплатно, без сервера).
"""

import os
import random
import sys
import datetime
import re
import feedparser
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

POSTED_FILE = "posted.txt"

# 5 слотов публикации в UTC (06:00, 09:30, 13:00, 16:30, 20:00 по Москве = UTC+3)
ALLOWED_UTC_HOURS = {3, 6, 10, 13, 17}

RSS_FEEDS = [
    "https://nplus1.ru/rss",                   # N+1 (наука и техника)
    "https://elementy.ru/rss/news",            # Элементы (научно-популярный)
    "https://nauka.tass.ru/rss/v2.xml",        # ТАСС Наука
    "https://www.popmech.ru/rss/all.xml",      # Популярная механика
    "https://www.techinsider.ru/rss/all.xml",  # TechInsider (курьёзы и техника)
    "https://science.ru/rss/news"              # Наука.ру
]

# Ключевые слова, которые НЕ попадают в канал
BLOCKED_KEYWORDS = [
    "сво", "спецоперац", "украин", "україн", "зеленск",
    "zelensky", "zelenskyy", "kiev", "kyiv",
    "донбасс", "донецк", "луганск", "киев",
    "всу", "кремль", "путин", "харьков", "одесс",
    "мариупол", "бахмут", "курск", "белгород",
]

# Регулярное выражение для проверки наличия русских букв
RUSSIAN_RE = re.compile('[а-яА-ЯёЁ]')

def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def fetch_entries():
    entries = []
    for url in RSS_FEEDS: # ИСПРАВЛЕНО: было FEEDS
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:15]:
                link = getattr(e, "link", "")
                title = getattr(e, "title", "").strip()
                summary = getattr(e, "summary", "")
                
                # Проверяем, что заголовок на русском (содержит русские буквы)
                if link and title and RUSSIAN_RE.search(title):
                    entries.append({"title": title, "link": link, "text": f"{title} {summary}".lower()})
        except Exception:
            continue
    return entries

def is_blocked(entry):
    text = entry["text"]
    return any(kw in text for kw in BLOCKED_KEYWORDS)

def post_to_channel(entry):
    text = f'<b>{entry["title"]}</b>\n\n<a href="{entry["link"]}">Читать полностью</a>'
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHANNEL_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    return resp.ok, resp.text

def main():
    # Ручной запуск (workflow_dispatch) — публикуем в любом случае
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        hour = datetime.datetime.now(datetime.timezone.utc).hour
        if hour not in ALLOWED_UTC_HOURS:
            print(f"Не слот публикации (UTC hour={hour}), выход.")
            return

    posted = load_posted()
    entries = [e for e in fetch_entries() if not is_blocked(e)]
    fresh = [e for e in entries if e["link"] not in posted]

    if not fresh:
        print("Нет свежих новостей — выход.")
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
