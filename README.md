# SINTA Journal Accreditation Rank Tracker & Dashboard

Sinta Tracker is a premium, lightweight, automated system designed to monitor, track, and alert you on data integrity changes of **SINTA (Science and Technology Index)** journal accreditation ranks. It filters specifically for IT-related journals and displays them in a gorgeous real-time interactive dashboard.

Features include multi-platform webhook notifications (Discord & Telegram) when an accreditation rank changes, automated database sync, session-aware bulk crawling, and a highly polished, premium glassmorphic web interface.

---

## 🌟 Key Features

* **Smart Bulk Crawling & Seeding**:
  - Automatically queries SINTA's journal databases by Subject Area Category IDs (e.g., Science and Engineering).
  - Performs intelligent client-side keyword matching for IT/Computer Science topics to build a targeted monitoring list.
  - Features session restoration to prevent context loss during pagination.

* **Precise Accreditation Monitoring**:
  - Leverages robust targeted scraping to verify the exact current rank directly from SINTA journal profile pages.
  - Automatically records historical data and saves updates to a local SQLite database.
  - Protects SINTA's servers with built-in rate-limiting, request retries, and timing jitter.

* **Instant Webhook Alerts**:
  - Dispatches immediate structured rich embed alerts to **Discord** and HTML-formatted notifications to **Telegram** when a change is detected.
  - Built-in high-severity notifications if the ratio of "Unknown" ranks exceeds 10%, indicating SINTA site layout changes or potential rate limit blocking.

* **Premium Interactive Dashboard**:
  - Built using Flask and a beautifully designed custom dark-mode theme.
  - Features real-time live data queries, searchable journal indices, pagination, filterable categories, and instant configuration inspection (with masked secure webhooks).

---

## 🛠️ Architecture & Tech Stack

* **Backend**: Python 3, Flask, SQLite, BeautifulSoup4, Requests
* **Deployment**: Configured for standard WSGI servers, compatible with Nixpacks, Docker, and direct Procfile runners (Railway, Heroku, Render)
* **Design & Frontend**: Modern HTML5, custom styled Tailwind CSS, high-performance vanilla JS dynamic data tables

---

## 🚀 Getting Started

### 1. Prerequisites
Make sure you have **Python 3.8+** installed.

### 2. Installation
Clone this repository and install the dependencies:
```bash
git clone https://github.com/your-username/deteksi-perubahan-jurnal.git
cd deteksi-perubahan-jurnal
pip install -r requirements.txt
```

### 3. Environment & Configuration
Copy the `.env.example` file to `.env`:
```bash
cp .env.example .env
```

Configure your Discord and Telegram webhooks in `config.json`:
```json
{
    "webhook": {
        "discord_url": "YOUR_DISCORD_WEBHOOK_URL",
        "telegram_bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
        "telegram_chat_id": "YOUR_TELEGRAM_CHAT_ID"
    },
    "scraping": {
        "timeout_seconds": 10,
        "delay_between_requests": 2.0,
        "max_retries": 3,
        "loop_interval_seconds": 86400
    }
}
```

---

## 🕹️ CLI Usage Instructions

The monitoring engine `sinta_tracker.py` is fully command-line driven. Run it with the following options:

* **Initialize Database & Seed Journals**:
  Crawls SINTA categories, filters for IT relevance, writes to the SQLite database, and populates `config.json`:
  ```bash
  python sinta_tracker.py --init
  ```

* **Manually Trigger a Scraping Verification Cycle**:
  Scrapes each monitored journal's profile page and updates the database, dispatching webhook notifications on rank mismatches:
  ```bash
  python sinta_tracker.py --scrape
  ```
  *(To test a single journal, specify its ID: `python sinta_tracker.py --scrape --id 1093`)*

* **Simulate a Rank Change (For Webhook Testing)**:
  Forces the database rank of a journal ID to a mock value, allowing you to test the change detection logic in your next `--scrape` run:
  ```bash
  python sinta_tracker.py --set-rank 1093 S1
  ```

* **Start the Scheduled Scraper Daemon**:
  Runs continuously in the background, executing scraping cycles at the interval configured in `config.json` (minimum 6 hours with built-in timing jitter):
  ```bash
  python sinta_tracker.py --loop
  ```

---

## 🖥️ Running the Dashboard

Launch the gorgeous interactive Flask dashboard:
```bash
python dashboard.py
```
By default, the server will start at `http://localhost:5000`.

* In production, the port can be custom configured via the `PORT` environment variable.
* Flask debug mode can be enabled by setting the environment variable `FLASK_DEBUG=1`.

---

## 📂 Project Structure

```
├── templates/
│   └── dashboard.html       # Single Page Interactive Web App Template
├── dashboard.py             # Flask Web Server
├── sinta_tracker.py         # Crawler, Scraper, CLI Engine & Alerts
├── config.json              # Scraping rules and target SINTA journal lists
├── Procfile                 # Deployment process declaration for Railway/Heroku
├── railway.json             # Deployment settings for Railway
├── .env.example             # Template for local environment configs
├── .gitignore               # Strict exclude patterns for database, logs, temp files
└── requirements.txt         # Core dependencies
```

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
