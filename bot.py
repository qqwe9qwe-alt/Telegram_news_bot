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
TAGS_RE = re.compile(r'<[^>]+>')

def clean_html(raw_html):
    if not raw_html:
        return ""
    clean_text = unescape(TAGS_RE.sub('', raw_html))
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

# --- НОВАЯ ФУНКЦИЯ: Поиск картинки в новости ---
def extract_image(entry):
    # 1. Ищем стандартные медиа-вложения (media_content, media_thumbnail)
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            if media.get('url'):
                return media.get('url')
    
    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        return entry.media_thumbnail[0].get('url')
        
    # 2. Ищем прикрепленные файлы (enclosures)
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if 'image' in enc.get('type', ''):
                return enc.get('href')
                
    # 3. Ищем тег <img> внутри описания (summary)
    raw_summary = getattr(entry, "summary", "")
    if raw_summary:
        img_match = re.search(r'<img[^>]+src="([^">]+)"', raw_summary)
        if img_match:
            return img_match.group(1)
            
    return None

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
                raw_summary = getattr(e, "summary", "")
                summary = clean_html(raw_summary)
                
                # Ищем картинку
                image_url = extract_image(e)
                
                if link and title and RUSSIAN_RE.search(title):
                    entries.append({
                        "title": title, 
                        "link": link, 
                        "text": f"{title} {summary}".lower(),
                        "summary": summary,
                        "image_url": image_url # Сохраняем ссылку на картинку
                    })
        except Exception:
            continue
    return entries

def is_blocked(entry):
    text = entry["text"]
    return any(kw in text for kw in BLOCKED_KEYWORDS)

def post_to_channel(entry):
    summary_text = entry["summary"]
    if len(summary_text) > 800:
        summary_text = summary_text[:800] + "..."
    
    if not summary_text:
        summary_text = "Подробности в источнике."

    # Формируем подпись (текст под картинкой)
    # Лимит подписи к фото в Telegram - 1024 символа
    caption = f'<b>{entry["title"]}</b>\n\n{summary_text}'
    
    # Если картинка найдена, отправляем фото с подписью
    if entry.get("image_url"):
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            json={
                "chat_id": CHANNEL_ID,
                "photo": entry["image_url"],
                "caption": caption[:1024], # Обрезаем на всякий случай
                "parse_mode": "HTML",
            },
            timeout=30,
        )
        # Если Telegram не смог скачать картинку по ссылке (битая/закрытая), 
        # отправляем просто текст
        if not resp.ok:
            print(f"Не удалось отправить фото ({resp.text}), отправляю текст.")
            return post_text_fallback(entry, caption)
        return True, resp.text
    else:
        # Если картинки нет, отправляем просто текст
        return post_text_fallback(entry, caption)

def post_text_fallback(entry, caption):
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHANNEL_ID,
            "text": caption[:4096], # Лимит текста в Telegram - 4096
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
