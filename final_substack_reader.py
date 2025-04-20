import feedparser
import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import datetime, timedelta
from time import sleep

# === TELEGRAM BOT CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# === Hugging Face API Key ===
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# === Escape Markdown characters for Telegram (MarkdownV2 mode) ===
def escape_markdown(text):
    escape_chars = r"_*[]()~`>#+=|{}.!-"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

# === Fetch article content from URL ===
def get_article_content(url, retries=3, timeout=10):
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        soup = BeautifulSoup(response.content, "html.parser")
        content_div = soup.find("div", class_="body") or soup.find("article")
        return content_div.get_text(separator="\n", strip=True) if content_div else "Content not found."
    except requests.exceptions.Timeout:
        if retries > 0:
            sleep(2)
            return get_article_content(url, retries-1)
        return "Timeout fetching article."
    except Exception as e:
        return f"Error fetching article: {e}"

# === Summarize article using Hugging Face API ===
def summarize_article(content):
    api_url = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
        "Content-Type": "application/json"
    }

    truncated_content = content[:3000]
    payload = {
        "inputs": truncated_content,
        "parameters": {"max_new_tokens": 300}
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        result = response.json()

        if isinstance(result, list):
            item = result[0]
            if "generated_text" in item:
                return item["generated_text"]
            elif "summary_text" in item:
                return item["summary_text"]
            else:
                return f"⚠️ Unexpected response keys: {list(item.keys())}"
        elif isinstance(result, dict) and "error" in result:
            return f"⚠️ Hugging Face API error: {result['error']}"
        else:
            return f"⚠️ Unexpected response format: {result}"
    except Exception as e:
        return f"❌ Error summarizing: {e}"


# === Send message(s) to Telegram with automatic splitting ===
def send_telegram_messages(full_text):
    chunks = []
    while full_text:
        if len(full_text) <= 4096:
            chunks.append(full_text)
            break
        split_index = full_text.rfind("\n---\n", 0, 4096)
        if split_index == -1:
            split_index = 4096
        chunks.append(full_text[:split_index])
        full_text = full_text[split_index:].lstrip()

    for idx, chunk in enumerate(chunks):
        escaped_chunk = escape_markdown(chunk)
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": escaped_chunk,
            "parse_mode": "MarkdownV2"
        }
        res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=payload)
        if res.status_code == 200:
            print(f"✅ Message {idx + 1} sent.")
        else:
            print(f"❌ Telegram error in chunk {idx + 1}: {res.json()}")

# === Get yesterday's date ===
yesterday = (datetime.now() - timedelta(days=1)).date()

# === Load feed URLs from file ===
with open("clean_substack_feeds.txt", "r") as f:
    feeds = [line.strip() for line in f if line.strip()]

# === Initialize message text ===
full_message = "📰 *Substack Summary Bot*\n\n"

# === Loop through feeds and summarize yesterday's posts ===
for feed_url in feeds:
    print(f"\nFetching RSS feed: {feed_url}...")
    try:
        response = requests.get(feed_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        feed = feedparser.parse(response.content)
    except requests.exceptions.Timeout:
        print(f"❌ Timeout fetching feed: {feed_url}")
        continue
    except Exception as e:
        print(f"❌ Failed to fetch feed {feed_url}: {e}")
        continue

    for entry in feed.entries:
        published_str = entry.get("published", "")
        if 'GMT' in published_str:
            published_str = published_str.replace('GMT', '+0000')

        try:
            pub_date = datetime.strptime(published_str, "%a, %d %b %Y %H:%M:%S %z").date()
        except Exception as e:
            print(f"⚠️ Skipping '{entry.get('title')}' due to date parsing error: {e}")
            continue

        if pub_date == yesterday:
            print(f"✅ Found: {entry.title}")
            content = get_article_content(entry.link)
            summary = summarize_article(content)
            full_message += f"*{entry.title}*\n{entry.link}\n_{summary}_\n\n---\n"

# === Send the message(s) ===
if full_message.strip() == "📰 *Substack Summary Bot*":
    send_telegram_messages("📰 *Substack Summary Bot*\n\nNo new posts found for yesterday.")
else:
    send_telegram_messages(full_message)
