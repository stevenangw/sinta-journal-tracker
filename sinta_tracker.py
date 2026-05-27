#!/usr/bin/env python3
"""
Sinta Tracker - Lightweight SINTA Journal Accreditation Rank Monitor
Monitors and tracks data integrity of SINTA journal accreditation ranks.
Sends alerts via Discord/Telegram webhooks when changes are detected.
"""

import os
import re
import sys
import json
import time
import random
import logging
import logging.handlers
import sqlite3
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Define constants
DB_NAME = "sinta_tracker.db"
CONFIG_NAME = os.environ.get("SINTA_CONFIG_PATH", "config.json")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# SINTA Category/Subject Area IDs mapped to their filter values.
# To verify or update these IDs if SINTA updates their backend:
# 1. Open a browser and navigate to SINTA's journal listing page (https://sinta.kemdiktisaintek.go.id/journals).
# 2. Open Developer Tools (F12 or Ctrl+Shift+I).
# 3. Open the filter modal, inspect the checkbox elements for the Subject Areas,
#    and look at their 'name' attributes (e.g. name="filter_area[5]") and 'value' attributes (e.g. value="5").
# 4. Map the category name to its integer value here.
SINTA_CATEGORY_IDS = {
    "science": 5,
    "engineering": 10,
}

# Setup logging
log_handlers = [
    logging.StreamHandler(sys.stdout)
]

try:
    file_handler = logging.handlers.RotatingFileHandler(
        "tracker.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    log_handlers.append(file_handler)
except Exception as e:
    print(f"Failed to initialize file logging: {e}", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=log_handlers
)
def get_db_path(db_path: Optional[str] = None) -> str:
    if db_path is not None and db_path != DB_NAME:
        return db_path
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return DB_NAME
    if db_url.startswith("sqlite:///"):
        return db_url[len("sqlite:///"):]
    return db_url


def load_config(config_path: str = CONFIG_NAME) -> Dict:
    """Loads application configuration, prioritizing environment variables."""
    config_data = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            logging.error(f"Failed to parse config file: {e}")
    else:
        logging.warning(f"Config file '{config_path}' not found.")

    if "webhook" not in config_data:
        config_data["webhook"] = {}
    if "scraping" not in config_data:
        config_data["scraping"] = {
            "timeout_seconds": 10,
            "delay_between_requests": 2.0,
            "max_retries": 3,
            "loop_interval_seconds": 86400,
            "enable_keyword_filter": False,
            "keyword_filter_terms": []
        }
    if "journals" not in config_data:
        config_data["journals"] = []

    # Override with env variables if present
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if discord_url:
        config_data["webhook"]["discord_url"] = discord_url

    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if telegram_token:
        config_data["webhook"]["telegram_bot_token"] = telegram_token

    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if telegram_chat_id:
        config_data["webhook"]["telegram_chat_id"] = telegram_chat_id

    return config_data


def save_config(config_data: Dict, config_path: str = CONFIG_NAME) -> None:
    """Saves application configuration to JSON."""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        logging.info(f"Configuration saved to '{config_path}'")
    except Exception as e:
        logging.error(f"Failed to save config file: {e}")


def init_db(db_path: str = DB_NAME) -> None:
    """Initializes the SQLite database, ensures table exists, and creates database indexes."""
    db_path = get_db_path(db_path)
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS journals (
                id INTEGER PRIMARY KEY,
                journal_name TEXT NOT NULL,
                sinta_url TEXT UNIQUE NOT NULL,
                current_rank TEXT NOT NULL,
                previous_rank TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        try:
            cursor.execute("ALTER TABLE journals ADD COLUMN previous_rank TEXT")
        except sqlite3.OperationalError:
            pass

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_journals_current_rank ON journals (current_rank)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_journals_last_updated ON journals (last_updated)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_journals_journal_name ON journals (journal_name)")

        conn.commit()
        conn.close()
        logging.info("Database and table 'journals' initialized successfully with indexes.")
    except Exception as e:
        logging.critical(f"Database initialization failed: {e}")
        sys.exit(1)


def get_db_connection(db_path: str = DB_NAME) -> sqlite3.Connection:
    """Returns a connection to the SQLite database."""
    db_path = get_db_path(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def save_journal_to_db(
    journal_id: int,
    name: str,
    url: str,
    rank: str,
    db_path: str = DB_NAME
) -> bool:
    """Upserts a journal record into the database."""
    db_path = get_db_path(db_path)
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO journals (id, journal_name, sinta_url, current_rank, previous_rank, last_updated)
            VALUES (?, ?, ?, ?, NULL, ?)
            ON CONFLICT(sinta_url) DO UPDATE SET
                journal_name=excluded.journal_name,
                previous_rank=CASE WHEN current_rank != excluded.current_rank THEN current_rank ELSE previous_rank END,
                current_rank=excluded.current_rank,
                last_updated=excluded.last_updated
            """,
            (journal_id, name, url, rank, now)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error saving journal ID {journal_id} to DB: {e}")
        return False


def get_all_journals_from_db(db_path: str = DB_NAME) -> List[Dict]:
    """Retrieves all monitored journals from the database."""
    db_path = get_db_path(db_path)
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, journal_name, sinta_url, current_rank, previous_rank, last_updated FROM journals")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"Error fetching journals from database: {e}")
        return []


def update_journal_rank_in_db(
    journal_id: int,
    new_rank: str,
    db_path: str = DB_NAME
) -> None:
    """Updates the rank and timestamp for a journal in the database."""
    db_path = get_db_path(db_path)
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            "UPDATE journals SET previous_rank = current_rank, current_rank = ?, last_updated = ? WHERE id = ?",
            (new_rank, now, journal_id)
        )
        conn.commit()
        conn.close()
        logging.info(f"Database updated for journal ID {journal_id}: current_rank -> {new_rank}")
    except Exception as e:
        logging.error(f"Failed to update database for journal ID {journal_id}: {e}")


def parse_profile_rank(html: str) -> str:
    """Parses SINTA rank from the journal profile page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Look inside class "stat-num" for text containing Sinta 1-6
    for el in soup.find_all(class_="stat-num"):
        text = el.get_text(strip=True)
        match = re.search(r'Sinta\s*([1-6])', text, re.IGNORECASE)
        if match:
            return f"S{match.group(1)}"
            
    # 2. Fallback to searching all text for "Sinta 1-6"
    for el in soup.find_all(string=re.compile(r'Sinta\s*[1-6]', re.IGNORECASE)):
        match = re.search(r'Sinta\s*([1-6])', el, re.IGNORECASE)
        if match:
            return f"S{match.group(1)}"
            
    return "Unknown"


def scrape_journal_profile(
    url: str,
    timeout: int = 10,
    max_retries: int = 3
) -> Optional[str]:
    """Targeted fetch for a single journal profile page and extracts its accreditation rank."""
    headers = {"User-Agent": USER_AGENT}
    
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            logging.info(f"HTTP {r.status_code}: Fetched profile URL {url} (Attempt {attempt}/{max_retries})")
            if r.status_code == 200:
                rank = parse_profile_rank(r.text)
                return rank
            else:
                logging.warning(f"Non-200 response ({r.status_code}) for URL: {url}")
        except requests.RequestException as e:
            logging.warning(f"Connection error on attempt {attempt} for URL {url}: {e}")
        
        if attempt < max_retries:
            time.sleep(2.0)
            
    return None


def send_webhook_alert(
    config: Dict,
    journal_name: str,
    old_rank: str,
    new_rank: str,
    sinta_url: str
) -> None:
    """Sends rank mismatch notifications to Discord and/or Telegram webhooks."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Send Discord notification
    discord_url = config.get("webhook", {}).get("discord_url")
    if discord_url:
        payload = {
            "embeds": [
                {
                    "title": "⚠️ SINTA RANK CHANGE DETECTED",
                    "color": 16753920,  # Orange color code
                    "fields": [
                        {"name": "Journal Name", "value": journal_name, "inline": False},
                        {"name": "Accreditation Change", "value": f"`{old_rank}` -> `{new_rank}`", "inline": True},
                        {"name": "Detection Time", "value": timestamp, "inline": True},
                        {"name": "Profile Link", "value": f"[View Sinta Profile]({sinta_url})", "inline": False}
                    ]
                }
            ]
        }
        try:
            res = requests.post(discord_url, json=payload, timeout=10)
            if res.status_code in [200, 204]:
                logging.info(f"Discord webhook notification dispatched successfully for '{journal_name}'.")
            else:
                logging.error(f"Discord webhook failed with code {res.status_code}: {res.text}")
        except Exception as e:
            logging.error(f"Failed to dispatch Discord webhook: {e}")

    # Send Telegram notification
    telegram_token = config.get("webhook", {}).get("telegram_bot_token")
    telegram_chat_id = config.get("webhook", {}).get("telegram_chat_id")
    if telegram_token and telegram_chat_id:
        text = (
            "⚠️ <b>SINTA RANK CHANGE DETECTED</b>\n\n"
            f"<b>Journal:</b> {journal_name}\n"
            f"<b>Change:</b> <code>{old_rank}</code> -> <code>{new_rank}</code>\n"
            f"<b>Detected At:</b> {timestamp}\n"
            f"<b>Link:</b> <a href=\"{sinta_url}\">Sinta Profile Page</a>"
        )
        telegram_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        payload = {
            "chat_id": telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            res = requests.post(telegram_url, json=payload, timeout=10)
            if res.status_code == 200:
                logging.info(f"Telegram alert dispatched successfully for '{journal_name}'.")
            else:
                logging.error(f"Telegram webhook failed with code {res.status_code}: {res.text}")
        except Exception as e:
            logging.error(f"Failed to dispatch Telegram webhook: {e}")


def send_unknown_threshold_alert(
    config: Dict,
    unknown_count: int,
    total_count: int
) -> None:
    """Sends a high-severity alert to Discord and Telegram if the percentage of Unknown ranks exceeds 10%."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    percentage = (unknown_count / total_count) * 100
    
    # Send Discord notification
    discord_url = config.get("webhook", {}).get("discord_url")
    if discord_url:
        payload = {
            "embeds": [
                {
                    "title": "🚨 HIGH SEVERITY ALERT: EXCEEDED UNKNOWN RANK THRESHOLD",
                    "color": 16711680,  # Red color code
                    "description": (
                         f"**Warning:** A high percentage of monitored journals have an `Unknown` accreditation rank.\n"
                         f"This might indicate that **SINTA's HTML structure has changed**, or the scraper is getting blocked/restricted."
                    ),
                    "fields": [
                        {"name": "Unknown Rank Count", "value": f"`{unknown_count}`", "inline": True},
                        {"name": "Total Monitored Journals", "value": f"`{total_count}`", "inline": True},
                        {"name": "Percentage", "value": f"`{percentage:.2f}%` (Threshold: `10.00%`)", "inline": True},
                        {"name": "Detection Time", "value": timestamp, "inline": False}
                    ]
                }
            ]
        }
        try:
            res = requests.post(discord_url, json=payload, timeout=10)
            if res.status_code in [200, 204]:
                logging.info("Discord Unknown Rank Threshold alert dispatched successfully.")
            else:
                logging.error(f"Discord Unknown Rank Threshold alert failed with code {res.status_code}: {res.text}")
        except Exception as e:
            logging.error(f"Failed to dispatch Discord Unknown Rank Threshold alert: {e}")

    # Send Telegram notification
    telegram_token = config.get("webhook", {}).get("telegram_bot_token")
    telegram_chat_id = config.get("webhook", {}).get("telegram_chat_id")
    if telegram_token and telegram_chat_id:
        text = (
            "🚨 <b>HIGH SEVERITY ALERT: EXCEEDED UNKNOWN RANK THRESHOLD</b>\n\n"
            "<b>Warning:</b> A high percentage of monitored journals have an <code>Unknown</code> accreditation rank.\n"
            "This might indicate that <b>SINTA's HTML structure has changed</b>, or the scraper is getting blocked/restricted.\n\n"
            f"<b>Unknown Rank Count:</b> <code>{unknown_count}</code>\n"
            f"<b>Total Monitored Journals:</b> <code>{total_count}</code>\n"
            f"<b>Percentage:</b> <code>{percentage:.2f}%</code> (Threshold: 10.00%)\n"
            f"<b>Detected At:</b> {timestamp}"
        )
        telegram_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        payload = {
            "chat_id": telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            res = requests.post(telegram_url, json=payload, timeout=10)
            if res.status_code == 200:
                logging.info("Telegram Unknown Rank Threshold alert dispatched successfully.")
            else:
                logging.error(f"Telegram Unknown Rank Threshold alert failed with code {res.status_code}: {res.text}")
        except Exception as e:
            logging.error(f"Failed to dispatch Telegram Unknown Rank Threshold alert: {e}")


def crawl_sinta_category_bulk(
    categories: List[int],
    delay: float = 2.0,
    timeout: int = 10,
    max_retries: int = 3,
    config: Dict = None
) -> List[Dict]:
    """
    Crawls SINTA journal listing page using category filters.
    Applies filters via POST, paginates via GET with session checks,
    filters by IT keywords client-side (if enabled), and deduplicates the results.
    """
    if config is None:
        config = load_config()

    enable_keyword_filter = config.get("scraping", {}).get("enable_keyword_filter", False)
    keyword_terms = config.get("scraping", {}).get("keyword_filter_terms", [])
    
    it_pattern = None
    if enable_keyword_filter:
        if keyword_terms:
            escaped_terms = [re.escape(t) for t in keyword_terms if t.strip()]
            if escaped_terms:
                it_pattern = re.compile(r'(' + '|'.join(escaped_terms) + r')', re.IGNORECASE)
        
        if not it_pattern:
            it_pattern = re.compile(
                r'(komputer|computer|comput|informatika|informatik|informatic|sistem informasi|information system|'
                r'teknologi informasi|information technology|software|jaringan|network|multimedia|telecommunication|'
                r'telekomunikasi|elektronik|electro|electron|computing|digital|web|embedded|data science|sains data|'
                r'artificial intelligence|kecerdasan buatan|intelligence|intelligent|robot|game|telematika|telematics|siber|cyber|'
                r'kripto|crypto|database|basis data)', re.IGNORECASE
            )

    headers = {"User-Agent": USER_AGENT}
    discovered_journals = {}

    session = requests.Session()
    session.headers.update(headers)

    base_url = "https://sinta.kemdiktisaintek.go.id/journals"

    for cat_id in categories:
        logging.info(f"Starting crawl for Category ID: {cat_id}...")
        
        page = 1
        while True:
            url = f"{base_url}?page={page}&filter_journals=1&filter_area[{cat_id}]={cat_id}"
            
            # Retrieve page html with retries
            html = None
            for attempt in range(1, max_retries + 1):
                try:
                    r = session.get(url, timeout=timeout)
                    if r.status_code != 200:
                        logging.warning(f"HTTP {r.status_code} on GET page {page} of Category {cat_id}")
                        time.sleep(2.0)
                        continue
                    
                    # We can parse right away
                    soup = BeautifulSoup(r.text, "html.parser")
                    name_divs = soup.find_all(class_="affil-name mb-3")
                    
                    html = r.text
                    break
                except requests.RequestException as e:
                    logging.warning(f"Request exception on GET page {page} of Category {cat_id}: {e}")
                    time.sleep(2.0)

            if not html:
                logging.error(f"Failed to fetch page {page} of Category {cat_id} after {max_retries} attempts. Aborting category crawl.")
                break

            # Parse journals
            soup = BeautifulSoup(html, "html.parser")
            name_divs = soup.find_all(class_="affil-name mb-3")
            if not name_divs:
                logging.info(f"No journals found on page {page} of Category {cat_id}. Reached end.")
                break

            page_discovered_count = 0
            page_matched_count = 0
            page_skipped_count = 0

            for div in name_divs:
                link = div.find('a')
                if not link:
                    continue
                
                href = link.get('href', '')
                name = link.get_text(strip=True)
                
                # Extract SINTA ID
                match_id = re.search(r'/profile/(\d+)', href)
                if not match_id:
                    continue
                sinta_id = int(match_id.group(1))
                
                # Extract Accreditation Rank from listing card
                rank = "Unknown"
                card = div.parent
                accredited_el = card.find(class_=re.compile(r'accredited', re.IGNORECASE))
                if accredited_el:
                    txt = accredited_el.get_text()
                    match_rank = re.search(r'S([1-6])', txt, re.IGNORECASE)
                    if match_rank:
                        rank = f"S{match_rank.group(1)}"
                        
                sinta_url = f"https://sinta.kemdiktisaintek.go.id/journals/profile/{sinta_id}"
                page_discovered_count += 1
                
                # Keyword Filtering Logic
                if enable_keyword_filter and it_pattern:
                    if it_pattern.search(name):
                        page_matched_count += 1
                        discovered_journals[sinta_id] = {
                            "id": sinta_id,
                            "journal_name": name,
                            "sinta_url": sinta_url,
                            "current_rank": rank
                        }
                    else:
                        page_skipped_count += 1
                else:
                    page_matched_count += 1
                    discovered_journals[sinta_id] = {
                        "id": sinta_id,
                        "journal_name": name,
                        "sinta_url": sinta_url,
                        "current_rank": rank
                    }
            
            logging.info(
                f"Category {cat_id} Page {page}: Found {page_discovered_count} journals "
                f"(total: {len(discovered_journals)}, skipped: {page_skipped_count})"
            )
            
            # Move to next page
            page += 1
            time.sleep(delay)

    return list(discovered_journals.values())


def crawl_sinta_all(
    delay: float = 2.0,
    timeout: int = 10,
    max_retries: int = 3,
    config: Dict = None
) -> List[Dict]:
    """
    Crawls SINTA journal listing page without category filters.
    Applies filters via GET only, filters by IT keywords client-side (if enabled),
    and deduplicates the results.
    """
    if config is None:
        config = load_config()

    enable_keyword_filter = config.get("scraping", {}).get("enable_keyword_filter", False)
    keyword_terms = config.get("scraping", {}).get("keyword_filter_terms", [])
    
    it_pattern = None
    if enable_keyword_filter:
        if keyword_terms:
            escaped_terms = [re.escape(t) for t in keyword_terms if t.strip()]
            if escaped_terms:
                it_pattern = re.compile(r'(' + '|'.join(escaped_terms) + r')', re.IGNORECASE)
        
        if not it_pattern:
            it_pattern = re.compile(
                r'(komputer|computer|comput|informatika|informatik|informatic|sistem informasi|information system|'
                r'teknologi informasi|information technology|software|jaringan|network|multimedia|telecommunication|'
                r'telekomunikasi|elektronik|electro|electron|computing|digital|web|embedded|data science|sains data|'
                r'artificial intelligence|kecerdasan buatan|intelligence|intelligent|robot|game|telematika|telematics|siber|cyber|'
                r'kripto|crypto|database|basis data)', re.IGNORECASE
            )

    headers = {"User-Agent": USER_AGENT}
    discovered_journals = {}

    session = requests.Session()
    session.headers.update(headers)

    base_url = "https://sinta.kemdiktisaintek.go.id/journals"

    page = 1
    while True:
        url = f"{base_url}?page={page}"
        
        html = None
        for attempt in range(1, max_retries + 1):
            try:
                r = session.get(url, timeout=timeout)
                if r.status_code != 200:
                    logging.warning(f"HTTP {r.status_code} on GET page {page}")
                    time.sleep(2.0)
                    continue
                
                html = r.text
                break
            except requests.RequestException as e:
                logging.warning(f"Request exception on GET page {page}: {e}")
                time.sleep(2.0)

        if not html:
            logging.error(f"Failed to fetch page {page} after {max_retries} attempts. Aborting crawl.")
            break

        soup = BeautifulSoup(html, "html.parser")
        name_divs = soup.find_all(class_="affil-name mb-3")
        if not name_divs:
            logging.info(f"No journals found on page {page}. Reached end.")
            break

        page_discovered_count = 0
        page_matched_count = 0
        page_skipped_count = 0

        for div in name_divs:
            link = div.find('a')
            if not link:
                continue
            
            href = link.get('href', '')
            name = link.get_text(strip=True)
            
            match_id = re.search(r'/profile/(\d+)', href)
            if not match_id:
                continue
            sinta_id = int(match_id.group(1))
            
            rank = "Unknown"
            card = div.parent
            accredited_el = card.find(class_=re.compile(r'accredited', re.IGNORECASE))
            if accredited_el:
                txt = accredited_el.get_text()
                match_rank = re.search(r'S([1-6])', txt, re.IGNORECASE)
                if match_rank:
                    rank = f"S{match_rank.group(1)}"
                    
            sinta_url = f"https://sinta.kemdiktisaintek.go.id/journals/profile/{sinta_id}"
            page_discovered_count += 1
            
            if enable_keyword_filter and it_pattern:
                if it_pattern.search(name):
                    page_matched_count += 1
                    discovered_journals[sinta_id] = {
                        "id": sinta_id,
                        "journal_name": name,
                        "sinta_url": sinta_url,
                        "current_rank": rank
                    }
                else:
                    page_skipped_count += 1
            else:
                page_matched_count += 1
                discovered_journals[sinta_id] = {
                    "id": sinta_id,
                    "journal_name": name,
                    "sinta_url": sinta_url,
                    "current_rank": rank
                }
        
        logging.info(
            f"Page {page}: Found {page_discovered_count} journals "
            f"(total: {len(discovered_journals)}, skipped: {page_skipped_count})"
        )
        
        page += 1
        time.sleep(delay)

    return list(discovered_journals.values())


def execute_scrape_cycle(config: Dict, target_id: Optional[int] = None) -> None:
    """Performs a full scrape cycle, comparing current web ranks to database records."""
    journals = get_all_journals_from_db()
    if not journals:
        logging.warning("No journals found in database to monitor. Please run with --init or --import-all first.")
        return

    if target_id is not None:
        journals = [j for j in journals if j["id"] == target_id]
        if not journals:
            logging.error(f"Journal with ID {target_id} not found in database.")
            return

    logging.info(f"Starting scrape cycle for {len(journals)} journals...")
    
    timeout = config.get("scraping", {}).get("timeout_seconds", 10)
    # Ensure minimum 1-second delay during scrape cycles
    delay = max(1.0, config.get("scraping", {}).get("delay_between_requests", 2.0))
    max_retries = config.get("scraping", {}).get("max_retries", 3)
    
    mismatch_count = 0
    success_count = 0

    for idx, journal in enumerate(journals):
        journal_id = journal["id"]
        journal_name = journal["journal_name"]
        sinta_url = journal["sinta_url"]
        db_rank = journal["current_rank"]
        
        logging.info(f"[{idx+1}/{len(journals)}] Checking journal ID {journal_id}: '{journal_name}'")
        
        web_rank = scrape_journal_profile(sinta_url, timeout=timeout, max_retries=max_retries)
        if not web_rank:
            logging.error(f"Skipping update check for '{journal_name}' due to scraping failures.")
            time.sleep(delay)
            continue
            
        success_count += 1
        
        if web_rank != db_rank:
            logging.warning(
                f"[RANK MISMATCH] '{journal_name}' (ID: {journal_id}): "
                f"DB: '{db_rank}' vs Web: '{web_rank}'"
            )
            mismatch_count += 1
            # Update database
            update_journal_rank_in_db(journal_id, web_rank)
            # Send webhooks
            send_webhook_alert(config, journal_name, db_rank, web_rank, sinta_url)
        else:
            logging.info(f"Journal ID {journal_id} rank matches database status: '{db_rank}'.")
            
        # Respect server rate limit
        time.sleep(delay)

    logging.info(
        f"Scrape cycle finished. Successful requests: {success_count}/{len(journals)}. "
        f"Mismatches detected & updated: {mismatch_count}."
    )

    # Count journals currently holding "Unknown" rank in the database
    updated_journals = get_all_journals_from_db()
    total_count = len(updated_journals)
    if total_count > 0:
        unknown_count = sum(1 for j in updated_journals if j["current_rank"] == "Unknown")
        percentage = (unknown_count / total_count) * 100
        logging.info(f"Scrape cycle summary: {unknown_count}/{total_count} journals ({percentage:.2f}%) have 'Unknown' rank.")
        if percentage > 10.0:
            logging.warning(f"Warning: More than 10% of journals have 'Unknown' rank ({percentage:.2f}%). Dispatching high-severity alert.")
            send_unknown_threshold_alert(config, unknown_count, total_count)


def seed_from_config(config_path: str = CONFIG_NAME, db_path: str = DB_NAME) -> int:
    """
    Directly seeds the database from journals configured in config.json.
    Extracts the journal SINTA ID from sinta_url and sets current_rank to 'Unknown'.
    Returns the number of successfully seeded journals.
    """
    config_data = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            logging.error(f"Failed to parse config file: {e}")
            return 0
    else:
        logging.error(f"Config file '{config_path}' not found for seeding.")
        return 0

    journals = config_data.get("journals", [])
    if not journals:
        logging.warning("No journals found in config file to seed.")
        return 0

    init_db(db_path)
    imported_count = 0
    for journal in journals:
        name = journal.get("journal_name")
        url = journal.get("sinta_url")
        if not name or not url:
            continue
        
        # Extract SINTA ID
        match_id = re.search(r'/profile/(\d+)', url)
        if not match_id:
            logging.warning(f"Skipping journal '{name}' because SINTA ID could not be extracted from URL: '{url}'")
            continue
        sinta_id = int(match_id.group(1))

        # Check if already exists in DB to prevent unnecessary overwrites, or do an upsert with current_rank = 'Unknown' only if new
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT current_rank FROM journals WHERE id = ?", (sinta_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            # Already exists in DB, keep its existing rank
            logging.info(f"Journal ID {sinta_id} ('{name}') already exists in DB with rank '{row['current_rank']}'. Skipping duplicate seeding.")
            imported_count += 1
            continue

        success = save_journal_to_db(
            journal_id=sinta_id,
            name=name,
            url=url,
            rank="Unknown",
            db_path=db_path
        )
        if success:
            imported_count += 1

    logging.info(f"Seeded {imported_count} journals from config to DB.")
    return imported_count


def main() -> None:
    """CLI Entry Point."""
    parser = argparse.ArgumentParser(
        description="Sinta Tracker - Monitors and tracks SINTA journal accreditation ranks."
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize the database table and auto-crawl/seed all IT journals in bulk from SINTA."
    )
    parser.add_argument(
        "--import-all",
        action="store_true",
        help="Crawl SINTA search listings in bulk to import/sync all IT journals to database and config."
    )
    parser.add_argument(
        "--crawl-all",
        action="store_true",
        help="Crawl all SINTA journals without any category or keyword filters to fully populate the database."
    )
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Perform a single live scraping verification cycle over all monitored journals."
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuous interval checks according to configuration parameters in config.json."
    )
    parser.add_argument(
        "--set-rank",
        nargs=2,
        metavar=("JOURNAL_ID", "RANK"),
        help="Force edit a journal's rank in the database to test the change detection logic."
    )
    parser.add_argument(
        "--id",
        type=int,
        help="Optional. Target a single journal ID for scraping."
    )
    parser.add_argument(
        "--seed-from-config",
        action="store_true",
        help="Directly seed the database from journals configured in config.json without querying SINTA listings."
    )
    
    args = parser.parse_args()
    
    # Force help output if no arguments are provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    # Initialize configuration
    config = load_config()

    if args.seed_from_config:
        logging.info("Directly seeding database from config.json...")
        imported_count = seed_from_config()
        logging.info(f"Database seeding complete. Seeded {imported_count} journals.")
        sys.exit(0)

    if args.init:
        init_db()
        logging.info("Auto-crawling SINTA by category filters for IT-related journals to populate database...")
        categories = list(SINTA_CATEGORY_IDS.values())
        # Enforce minimum 2-second delay between requests during bulk crawl
        journals = crawl_sinta_category_bulk(categories, delay=2.0, config=config)
        
        logging.info(f"Bulk category crawl complete. Found {len(journals)} unique journals.")
        
        if len(journals) == 0:
            logging.info("SINTA category crawler returned 0 journals (likely due to HTTP 503 or server offline). "
                         "Automatically falling back to seeding target journals from config.json...")
            imported_count = seed_from_config()
            logging.info(f"Successfully seeded {imported_count} fallback journals from config.json to the database.")
        else:
            imported_count = 0
            config_journals = []
            for journal in journals:
                success = save_journal_to_db(
                    journal_id=journal["id"],
                    name=journal["journal_name"],
                    url=journal["sinta_url"],
                    rank=journal["current_rank"]
                )
                if success:
                    imported_count += 1
                    config_journals.append({
                        "journal_name": journal["journal_name"],
                        "sinta_url": journal["sinta_url"]
                    })
                    
            logging.info(f"Successfully seeded {imported_count} journals to the SQLite database.")
            
            # Save to config.json as well so the user can easily view or edit target URLs
            config["journals"] = config_journals
            save_config(config)
            logging.info("Database initialization and initial bulk seed complete.")

    elif args.import_all:
        init_db()
        logging.info("Running mass category import from SINTA...")
        categories = list(SINTA_CATEGORY_IDS.values())
        # Enforce minimum 2-second delay between requests during bulk crawl
        journals = crawl_sinta_category_bulk(categories, delay=2.0, config=config)
        
        if len(journals) == 0:
            logging.info("SINTA category crawler returned 0 journals (likely due to HTTP 503 or server offline). "
                         "Automatically falling back to seeding target journals from config.json...")
            imported_count = seed_from_config()
            logging.info(f"Successfully seeded {imported_count} fallback journals from config.json to the database.")
        else:
            imported_count = 0
            config_journals = []
            for journal in journals:
                success = save_journal_to_db(
                    journal_id=journal["id"],
                    name=journal["journal_name"],
                    url=journal["sinta_url"],
                    rank=journal["current_rank"]
                )
                if success:
                    imported_count += 1
                    config_journals.append({
                        "journal_name": journal["journal_name"],
                        "sinta_url": journal["sinta_url"]
                    })
                    
            config["journals"] = config_journals
            save_config(config)
            logging.info(f"Sync complete. Monitored list contains {imported_count} unique journals.")

    elif args.crawl_all:
        init_db()
        logging.info("Running complete crawl over all SINTA journals without any category or keyword filters...")
        journals = crawl_sinta_all(delay=2.0, config=config)
        
        imported_count = 0
        config_journals = []
        for journal in journals:
            success = save_journal_to_db(
                journal_id=journal["id"],
                name=journal["journal_name"],
                url=journal["sinta_url"],
                rank=journal["current_rank"]
            )
            if success:
                imported_count += 1
                config_journals.append({
                    "journal_name": journal["journal_name"],
                    "sinta_url": journal["sinta_url"]
                })
                
        config["journals"] = config_journals
        save_config(config)
        logging.info(f"Sync complete. Monitored list contains {imported_count} unique journals.")

    elif args.set_rank:
        init_db()
        journal_id_str, target_rank = args.set_rank
        try:
            journal_id = int(journal_id_str)
        except ValueError:
            logging.error("Journal ID must be a numeric integer.")
            sys.exit(1)
            
        target_rank = target_rank.upper()
        if not re.match(r'^S[1-6]$', target_rank):
            logging.warning("Warning: Rank is not a standard S1-S6 value (e.g. S1, S2, S3, S4, S5, S6). Proceeding anyway.")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT journal_name, current_rank FROM journals WHERE id = ?", (journal_id,))
        row = cursor.fetchone()
        
        if not row:
            logging.error(f"Journal with ID {journal_id} not found in database. Can't set rank.")
            conn.close()
            sys.exit(1)
            
        old_rank = row["current_rank"]
        cursor.execute("UPDATE journals SET current_rank = ? WHERE id = ?", (target_rank, journal_id))
        conn.commit()
        conn.close()
        
        logging.info(
            f"Successfully updated '{row['journal_name']}' (ID: {journal_id}) "
            f"in database: '{old_rank}' -> '{target_rank}'."
        )

    elif args.scrape:
        execute_scrape_cycle(config, target_id=args.id)

    elif args.loop:
        interval = config.get("scraping", {}).get("loop_interval_seconds", 86400)
        if interval < 21600:
            logging.warning(
                f"Configured loop_interval_seconds ({interval}s) is below the minimum limit of 6 hours (21600s). "
                f"Overriding to 21600 seconds."
            )
            interval = 21600
            
        logging.info(f"Sinta Tracker starting loop mode. Inter-cycle base interval: {interval} seconds.")
        
        try:
            while True:
                # Add jitter of up to +/- 5 minutes (300 seconds) to loop interval
                jitter = random.randint(-300, 300)
                # Enforce minimum actual_interval of 21600 seconds (6 hours) including jitter
                actual_interval = max(21600, interval + jitter)
                
                logging.info("Initiating scheduled scrape cycle...")
                execute_scrape_cycle(config, target_id=args.id)
                
                next_check = datetime.fromtimestamp(time.time() + actual_interval).strftime("%Y-%m-%d %H:%M:%S")
                logging.info(f"Cycle finished. Next check scheduled for {next_check} (sleeping {actual_interval}s).")
                time.sleep(actual_interval)
        except KeyboardInterrupt:
            logging.info("Loop check terminated by user.")


if __name__ == "__main__":
    main()
