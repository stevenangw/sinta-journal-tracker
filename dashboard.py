import os
import sqlite3
import json
from flask import Flask, jsonify, render_template, request
from sinta_tracker import load_config, save_config, send_webhook_alert

app = Flask(__name__)

# Configurable paths and ports via ENV
DB_PATH = "sinta_tracker.db"
CONFIG_PATH = os.environ.get("SINTA_CONFIG_PATH", "./config.json")


def get_db_connection():
    # Connect in read-only mode using SQLite URI
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def mask_webhook(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 8:
        return "..." + val
    return "..." + val[-8:]


def get_masked_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Mask webhook URLs/tokens
        webhook = data.get("webhook", {})
        masked_webhook = {
            "discord_url": mask_webhook(webhook.get("discord_url", "")),
            "telegram_bot_token": mask_webhook(webhook.get("telegram_bot_token", "")),
            "telegram_chat_id": mask_webhook(webhook.get("telegram_chat_id", ""))
        }
        return {
            "webhook": masked_webhook,
            "scraping": data.get("scraping", {})
        }
    except Exception as e:
        app.logger.error(f"Error reading config file: {e}")
        return {}


@app.route("/")
def index():
    return render_template("dashboard.html", active_tab="dashboard", config_data=None)


@app.route("/config")
def config():
    masked_config = get_masked_config()
    return render_template("dashboard.html", active_tab="config", config_data=masked_config)


@app.route("/api/config", methods=["POST"])
def api_save_config():
    try:
        payload = request.get_json() or {}
        
        # Load the real, unmasked config from disk
        config_data = load_config(CONFIG_PATH)
        
        if "webhook" not in config_data:
            config_data["webhook"] = {}
            
        # Update fields if present in the payload (only edit mode sends these)
        if "discord_url" in payload:
            config_data["webhook"]["discord_url"] = payload["discord_url"].strip()
            
        if "telegram_bot_token" in payload:
            config_data["webhook"]["telegram_bot_token"] = payload["telegram_bot_token"].strip()
            
        if "telegram_chat_id" in payload:
            config_data["webhook"]["telegram_chat_id"] = payload["telegram_chat_id"].strip()
            
        # Save real config back to disk
        save_config(config_data, CONFIG_PATH)
        
        # Return success with the newly masked config
        masked = get_masked_config()
        return jsonify({"success": True, "config": masked})
    except Exception as e:
        app.logger.error(f"Error saving config via API: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/config/test", methods=["POST"])
def api_test_config():
    try:
        payload = request.get_json() or {}
        platform = payload.get("platform")
        
        # Load the real config to get valid webhook credentials
        config_data = load_config(CONFIG_PATH)
        webhook = config_data.get("webhook", {})
        
        if platform == "discord":
            discord_url = webhook.get("discord_url", "")
            if not discord_url:
                return jsonify({"success": False, "error": "Discord Webhook URL is not configured."})
                
            # Dispatch test webhook
            send_webhook_alert(config_data, "[TEST] Jurnal Sistem Informasi", "S4", "S3", "https://sinta.kemdiktisaintek.go.id")
            return jsonify({"success": True})
            
        elif platform == "telegram":
            bot_token = webhook.get("telegram_bot_token", "")
            chat_id = webhook.get("telegram_chat_id", "")
            if not bot_token or not chat_id:
                return jsonify({"success": False, "error": "Telegram Bot Token or Chat ID is not configured."})
                
            # Dispatch test webhook
            send_webhook_alert(config_data, "[TEST] Jurnal Sistem Informasi", "S4", "S3", "https://sinta.kemdiktisaintek.go.id")
            return jsonify({"success": True})
            
        else:
            return jsonify({"success": False, "error": "Invalid platform specified."}), 400
    except Exception as e:
        app.logger.error(f"Error testing config via API: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/journals")
def api_journals():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, journal_name, sinta_url, current_rank, last_updated FROM journals")
        rows = cursor.fetchall()
        conn.close()

        journals = []
        for row in rows:
            journals.append({
                "id": row["id"],
                "journal_name": row["journal_name"],
                "sinta_url": row["sinta_url"],
                "current_rank": row["current_rank"],
                "last_updated": row["last_updated"]
            })
        return jsonify(journals)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Flask debug mode OFF by default, controllable via ENV FLASK_DEBUG=1
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    port_num = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port_num, debug=debug_mode)
