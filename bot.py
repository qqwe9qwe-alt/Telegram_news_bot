"""
Бот новостей в Telegram-канал (GitHub Actions, бесплатно, без сервера).

Публикация: 5 раз в день (06:00, 09:30, 13:00, 16:30, 20:00 по Москве).
Источники: RSS-ленты научных СМИ.
Фильтр: вырезает новости про СВО/Украину (тема Ирана — допустима).
Антидубли: posted.txt хранится в репозитории и коммитится после каждого поста.

Переменные окружения:
  BOT_TOKEN   — токен от @BotFather
  CHANNEL_ID  — @имя_канала или id (например, -1001234567890)
"""

import os
import random
import sys
import datetime
import feedparser
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

POSTED_FILE = "posted.txt"

# 5 слотов публикации в UTC (06:00, 09:30, 13:00, 16:30, 20:00 по Москве = UTC+3)
ALLOWED_UTC_HOURS = {3, 6, 10, 13, 17}

FEEDS = [
    "https://nplus1.ru/rss",                          # N+1 (наука)
    "https://www.sciencedaily.com/rss/top/science.xml",  # ScienceDaily
    "https://phys.org/rss-feed/",                     # Phys.org
    "https://www.popularmechanics.com/rss/all.xml",   # Popular Mechanics
    "https://elementy.ru/rss/news",                   # Элементы большой науки
]

# Ключевые слова, которые НЕ попадают в канал (тема СВО/Украины)
BLOCKED_KEYWORDS = [
    "сво", "спецоперац", "украин", "україн", "зеленск",
    "zelensky", "zelenskyy", "kiev", "kyiv",
    "донбасс", "донецк", "луганск", "киев",
    "всу", "кремль", "путин", "харьков", "одесс",
    "мариупол", "бахмут", "курск", "белгород",
]


def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def fetch_entries():
    entries = []
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:15]:
                link = getattr(e, "link", "")
                title = getattr(e, "title", "").strip()
                summary = getattr(e, "summary", "")
                if link and title:
                    entries.append({"title": title, "link": link, "text": f"{title} {summary}".lower()})
        except Exception:
            continue  # битая лента пропускается
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
