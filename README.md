# SINTA Journal Accreditation Rank Tracker

A Python-based automated monitoring system to track and alert on accreditation rank changes in SINTA (Science and Technology Index) journals. Specifically filtered for IT, Computer Science, and Engineering topics, this system keeps records in a local SQLite database and serves them through a lightweight web dashboard.

---

## 🛠️ Core Features

* **Targeted Crawling & Seeding**:
  - Automatically queries SINTA categories (e.g., Science and Engineering).
  - Filters journals based on client-side keyword matching for IT/Computer Science topics.
  - Built-in session state restoration to safely handle SINTA pagination.

* **Monitoring & Data Integrity**:
  - Scrapes SINTA journal profile pages to verify current accreditation ranks (S1–S6).
  - Stores historical ranks and scrape logs in SQLite.
  - Implements rate-limiting, requests retries, and jitter delays to protect upstream SINTA servers.

* **Notifications & Alerts**:
  - Sends immediate detailed alerts via Discord rich embeds or Telegram HTML messages when a rank change is detected.
  - Notifies on scraping anomalies (e.g., if >10% of queries yield "Unknown", indicating potential IP blocks or layout changes).

* **Web Dashboard**:
  - Lightweight Flask backend with a responsive academic-style dark/light interface.
  - Interactive searchable data table with fast server-side pagination (Alpine.js + DataTables).
  - Secure configuration viewer with masked credentials.

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.8+**
- **SQLite3**

### 2. Installation
Clone the repository and install the dependencies:
```bash
git clone https://github.com/stevenangw/sinta-journal-tracker.git
cd sinta-journal-tracker
pip install -r requirements.txt
```

### 3. Configuration
1. Copy the example environment template:
   ```bash
   cp .env.example .env
   ```
2. Configure webhook integrations and scrapers in `config.json`:
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

## 🕹️ CLI Usage

The core engine `sinta_tracker.py` is fully command-line driven.

* **Initialize Database & Seed Journals**:
  Crawls SINTA categories, filters for IT relevance, and writes them to the SQLite database:
  ```bash
  python sinta_tracker.py --init
  ```

* **Trigger a Scraping Verification Cycle**:
  Scrapes each monitored journal's profile page and updates the database, dispatching webhook notifications on rank changes:
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

Launch the Flask web dashboard:
```bash
python dashboard.py
```
By default, the server will start at `http://localhost:5000`.

- In production, specify the port using the `PORT` environment variable.
- Flask debug mode can be enabled by setting `FLASK_DEBUG=1`.

---

## 📂 Project Structure

```
├── templates/
│   └── dashboard.html       # Web App Frontend (Alpine.js + DataTables)
├── dashboard.py             # Flask Web Server
├── sinta_tracker.py         # Crawler, Scraper, CLI Engine & Alerts
├── config.json              # Scraping rules and target SINTA journal lists
├── Procfile                 # Process runner config (Railway/Heroku)
├── railway.json             # Deployment settings for Railway
├── .env.example             # Template for local environment configs
├── .gitignore               # Strict exclude patterns for database, logs, temp files
└── requirements.txt         # Core dependencies
```

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
