import os
import random
import sys
import datetime
import re
import feedparser
import requests
from html import unescape

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

POSTED_FILE = "posted.txt"

# 5 слотов публикации в UTC (06:00, 09:30, 13:00, 16:30, 20:00 по Москве = UTC+3)
ALLOWED_UTC_HOURS = {3, 6, 10, 13, 17}

RSS_FEEDS = [
    "https://nplus1.ru/rss",
    "https://elementy.ru/rss/news",
    "https://nauka.tass.ru/rss/v2.xml",
    "https://www.popmech.ru/rss/all.xml",
    "https://www.techinsider.ru/rss/all.xml",
    "https://science.ru/rss/news"
]

BLOCKED_KEYWORDS = [
    "сво", "спецоперац", "украин", "україн", "зеленск",
    "zelensky", "zelenskyy", "kiev", "kyiv",
    "донбасс", "донецк", "луганск", "киев",
    "всу", "кремль", "путин", "харьков", "одесс",
    "мариупол", "бахмут", "курск", "белгород",
]

RUSSIAN_RE = re.compile('[а-яА-ЯёЁ]')
TAGS_RE = re.compile(r'<[^>]+>') # Регулярка для удаления HTML-тегов

def clean_html(raw_html):
    """Очищает текст от HTML-тегов и лишних пробелов"""
    if not raw_html:
        return ""
    # Убираем HTML-теги и раскодируем спецсимволы (&nbsp;, &quot; и т.д.)
    clean_text = unescape(TAGS_RE.sub('', raw_html))
    # Убираем лишние пробелы и переносы строк
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def fetch_entries():
    entries = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:15]:
                link = getattr(e, "link", "")
                title = getattr(e, "title", "").strip()
                # Берем summary (краткое описание) и очищаем его
                raw_summary = getattr(e, "summary", "")
                summary = clean_html(raw_summary)
                
                if link and title and RUSSIAN_RE.search(title):
                    entries.append({
                        "title": title, 
                        "link": link, 
                        "text": f"{title} {summary}".lower(),
                        "summary": summary # Сохраняем очищенный текст
                    })
        except Exception:
            continue
    return entries

def is_blocked(entry):
    text = entry["text"]
    return any(kw in text for kw in BLOCKED_KEYWORDS)

def post_to_channel(entry):
    # Форматируем пост: Жирный заголовок + краткий текст
    # Если текст слишком длинный (больше 800 символов), обрезаем его
    summary_text = entry["summary"]
    if len(summary_text) > 800:
        summary_text = summary_text[:800] + "..."
    
    # Если описания нет, ставим заглушку
    if not summary_text:
        summary_text = "Подробности в источнике."

    text = f'<b>{entry["title"]}</b>\n\n{summary_text}'
    
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHANNEL_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True, # Отключаем предпросмотр ссылок (картинки)
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
