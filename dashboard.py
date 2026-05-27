import os
import sqlite3
import json
from flask import Flask, jsonify, render_template, request
from sinta_tracker import load_config, save_config, send_webhook_alert

app = Flask(__name__)

# Configurable paths and ports via ENV
DB_PATH = "sinta_tracker.db"
CONFIG_PATH = os.environ.get("SINTA_CONFIG_PATH", "./config.json")


def run_migrations():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE journals ADD COLUMN previous_rank TEXT")
            conn.commit()
            app.logger.info("Migration successful: added previous_rank column.")
        except sqlite3.OperationalError:
            # Column already exists
            pass
        conn.close()
    except Exception as e:
        app.logger.error(f"Migration error: {e}")

run_migrations()


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
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 50, type=int)
        if limit > 100:
            limit = 100
        elif limit < 1:
            limit = 50
            
        search = request.args.get("search", "").strip()
        rank_str = request.args.get("rank", "").strip()
        sort_col = request.args.get("sort", "last_updated").strip()
        sort_dir = request.args.get("dir", "desc").strip()
        
        if sort_dir.lower() not in ["asc", "desc"]:
            sort_dir = "asc"
            
        where_clauses = []
        params = []
        
        if search:
            where_clauses.append("journal_name LIKE ?")
            params.append(f"%{search}%")
            
        if rank_str:
            ranks = [r.strip() for r in rank_str.split(",") if r.strip()]
            if ranks:
                placeholders = ",".join(["?"] * len(ranks))
                where_clauses.append(f"current_rank IN ({placeholders})")
                params.extend(ranks)
                
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
            
        sort_field = "journal_name"
        if sort_col == "rank":
            sort_field = "CASE current_rank WHEN 'S1' THEN 1 WHEN 'S2' THEN 2 WHEN 'S3' THEN 3 WHEN 'S4' THEN 4 WHEN 'S5' THEN 5 WHEN 'S6' THEN 6 ELSE 7 END"
        elif sort_col == "last_updated":
            sort_field = "last_updated"
            
        order_sql = f"ORDER BY {sort_field} {sort_dir}"
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT current_rank, COUNT(*) as c FROM journals GROUP BY current_rank")
        stats_rows = cursor.fetchall()
        stats = {"S1": 0, "S2": 0, "S3": 0, "S4": 0, "S5": 0, "S6": 0, "Unknown": 0}
        for r in stats_rows:
            rank_key = r["current_rank"]
            count_val = r["c"]
            if rank_key in stats:
                stats[rank_key] = count_val
            elif not rank_key or rank_key == "Unknown":
                stats["Unknown"] += count_val
            else:
                stats["Unknown"] += count_val
                
        cursor.execute(f"SELECT COUNT(*) FROM journals {where_sql}", params)
        total_matching = cursor.fetchone()[0]
        
        offset = (page - 1) * limit
        limit_sql = "LIMIT ? OFFSET ?"
        query_params = params + [limit, offset]
        
        cursor.execute(f"SELECT id, journal_name, sinta_url, current_rank, previous_rank, last_updated FROM journals {where_sql} {order_sql} {limit_sql}", query_params)
        rows = cursor.fetchall()
        conn.close()
        
        journals = []
        for row in rows:
            journals.append({
                "id": row["id"],
                "journal_name": row["journal_name"],
                "sinta_url": row["sinta_url"],
                "current_rank": row["current_rank"],
                "previous_rank": row["previous_rank"],
                "last_updated": row["last_updated"]
            })
            
        total_pages = (total_matching + limit - 1) // limit if total_matching > 0 else 1
        
        return jsonify({
            "journals": journals,
            "meta": {
                "total": total_matching,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "stats": stats
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/changes")
def api_changes():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Query 10 journals where previous_rank is not NULL, and differs from current_rank
        cursor.execute(
            "SELECT id, journal_name, current_rank, previous_rank, last_updated "
            "FROM journals "
            "WHERE previous_rank IS NOT NULL AND previous_rank != '' AND previous_rank != 'None' AND previous_rank != current_rank "
            "ORDER BY last_updated DESC LIMIT 10"
        )
        rows = cursor.fetchall()
        conn.close()
        
        changes = []
        for r in rows:
            changes.append({
                "id": r["id"],
                "journal_name": r["journal_name"],
                "current_rank": r["current_rank"],
                "previous_rank": r["previous_rank"],
                "last_updated": r["last_updated"]
            })
        return jsonify({"changes": changes})
    except Exception as e:
        app.logger.error(f"Error fetching changes: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Flask debug mode OFF by default, controllable via ENV FLASK_DEBUG=1
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    port_num = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port_num, debug=debug_mode)
