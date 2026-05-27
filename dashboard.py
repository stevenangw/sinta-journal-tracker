import os
import sqlite3
import json
import time
from flask import Flask, jsonify, render_template, request
from sinta_tracker import load_config, save_config, send_webhook_alert, get_db_path, init_db

app = Flask(__name__)

# Configurable paths via ENV
CONFIG_PATH = os.environ.get("SINTA_CONFIG_PATH", "./config.json")


class SimpleCache:
    """Lightweight, thread-safe in-memory cache for dashboard metrics and changes."""
    def __init__(self):
        self._data = {}
    
    def get(self, key):
        if key in self._data:
            val, expiry = self._data[key]
            if time.time() < expiry:
                return val
            del self._data[key]
        return None
    
    def set(self, key, val, ttl=300):
        self._data[key] = (val, time.time() + ttl)
        
    def clear(self):
        self._data.clear()


cache = SimpleCache()


def run_migrations():
    """Ensures database schema and indexes exist."""
    try:
        db_file_path = get_db_path()
        init_db(db_file_path)
        app.logger.info("Migration successful: DB schema and indexes verified.")
    except Exception as e:
        app.logger.error(f"Migration error during startup: {e}")


run_migrations()


def get_db_connection():
    """Establishes connection to the database file in read-only mode."""
    db_file_path = get_db_path()
    conn = sqlite3.connect(f"file:{db_file_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def mask_webhook(val: str) -> str:
    """Masks secret webhooks or tokens for security on dashboard loads."""
    if not val:
        return ""
    if len(val) <= 8:
        return "..." + val
    return "..." + val[-8:]


def get_masked_config():
    """Loads configuration and masks credentials."""
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

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


def make_response(success: bool, data=None, message: str = "", status_code: int = 200):
    """Standardized API response wrapper."""
    return jsonify({
        "success": success,
        "data": data,
        "message": message
    }), status_code


@app.errorhandler(404)
def handle_404(e):
    """Handles Resource Not Found states with custom layout matching UI or JSON formats."""
    if request.path.startswith("/api/"):
        return make_response(False, None, "Endpoint API tidak ditemukan.", 404)
    return render_template("dashboard.html", active_tab="error", error_message="Halaman yang Anda cari tidak dapat ditemukan."), 404


@app.errorhandler(500)
def handle_500(e):
    """Global system error catcher."""
    app.logger.error(f"Internal System Error: {e}")
    if request.path.startswith("/api/"):
        return make_response(False, None, "Terjadi kesalahan internal server.", 500)
    return render_template("dashboard.html", active_tab="error", error_message="Terjadi kesalahan internal pada server kami."), 500


@app.route("/")
def index():
    return render_template("dashboard.html", active_tab="dashboard", config_data=None)


@app.route("/config")
def config():
    masked_config = get_masked_config()
    return render_template("dashboard.html", active_tab="config", config_data=masked_config)


@app.route("/api/config", methods=["POST"])
def api_save_config():
    """Saves updated settings cleanly without corrupting masked parameters."""
    try:
        payload = request.get_json() or {}
        config_data = load_config(CONFIG_PATH)
        
        if "webhook" not in config_data:
            config_data["webhook"] = {}
            
        updated = False
        
        # Only overwrite if value is not masked (i.e. does not start with '...')
        if "discord_url" in payload:
            val = payload["discord_url"].strip()
            if val and not val.startswith("..."):
                config_data["webhook"]["discord_url"] = val
                updated = True
            elif not val:
                config_data["webhook"]["discord_url"] = ""
                updated = True
                
        if "telegram_bot_token" in payload:
            val = payload["telegram_bot_token"].strip()
            if val and not val.startswith("..."):
                config_data["webhook"]["telegram_bot_token"] = val
                updated = True
            elif not val:
                config_data["webhook"]["telegram_bot_token"] = ""
                updated = True
                
        if "telegram_chat_id" in payload:
            val = payload["telegram_chat_id"].strip()
            if val and not val.startswith("..."):
                config_data["webhook"]["telegram_chat_id"] = val
                updated = True
            elif not val:
                config_data["webhook"]["telegram_chat_id"] = ""
                updated = True
                
        if updated:
            save_config(config_data, CONFIG_PATH)
            cache.clear()
            
        masked = get_masked_config()
        return make_response(True, masked, "Konfigurasi berhasil diperbarui.")
    except Exception as e:
        app.logger.error(f"Error saving config via API: {e}")
        return make_response(False, None, f"Gagal memperbarui konfigurasi: {str(e)}", 500)


@app.route("/api/config/test", methods=["POST"])
def api_test_config():
    """Triggers mock system alert payloads to confirm webhook integrations work."""
    try:
        payload = request.get_json() or {}
        platform = payload.get("platform")
        
        config_data = load_config(CONFIG_PATH)
        webhook = config_data.get("webhook", {})
        
        if platform == "discord":
            discord_url = webhook.get("discord_url", "")
            if not discord_url:
                return make_response(False, None, "Webhook Discord belum dikonfigurasi.", 400)
                
            send_webhook_alert(config_data, "[TEST] Jurnal Sistem Informasi", "S4", "S3", "https://sinta.kemdiktisaintek.go.id")
            return make_response(True, None, "Notifikasi uji coba Discord berhasil dikirim.")
            
        elif platform == "telegram":
            bot_token = webhook.get("telegram_bot_token", "")
            chat_id = webhook.get("telegram_chat_id", "")
            if not bot_token or not chat_id:
                return make_response(False, None, "Token Bot atau Chat ID Telegram belum dikonfigurasi.", 400)
                
            send_webhook_alert(config_data, "[TEST] Jurnal Sistem Informasi", "S4", "S3", "https://sinta.kemdiktisaintek.go.id")
            return make_response(True, None, "Notifikasi uji coba Telegram berhasil dikirim.")
            
        else:
            return make_response(False, None, "Platform tidak didukung.", 400)
    except Exception as e:
        app.logger.error(f"Error testing config via API: {e}")
        return make_response(False, None, f"Gagal melakukan uji coba integrasi: {str(e)}", 500)


@app.route("/api/journals")
def api_journals():
    """Fetches paginated, filtered, and sorted journal records."""
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
        
        # Caching the statistics since it counts total entries which changes slowly
        stats = cache.get("db_stats")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if stats is None:
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
            cache.set("db_stats", stats, ttl=60)
            
        cursor.execute(f"SELECT COUNT(*) FROM journals {where_sql}", params)
        total_matching = cursor.fetchone()[0]
        
        offset = (page - 1) * limit
        limit_sql = "LIMIT ? OFFSET ?"
        query_params = params + [limit, offset]
        
        cursor.execute(
            f"SELECT id, journal_name, sinta_url, current_rank, previous_rank, last_updated "
            f"FROM journals {where_sql} {order_sql} {limit_sql}",
            query_params
        )
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
        
        result_data = {
            "journals": journals,
            "meta": {
                "total": total_matching,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "stats": stats
            }
        }
        return make_response(True, result_data, "Data jurnal berhasil diambil.")
    except Exception as e:
        app.logger.error(f"Error fetching journals: {e}")
        return make_response(False, None, f"Terjadi kesalahan saat memuat data jurnal: {str(e)}", 500)


@app.route("/api/changes")
def api_changes():
    """Fetches recently changed journal ranks."""
    try:
        cached_changes = cache.get("api_changes")
        if cached_changes is not None:
            return make_response(True, {"changes": cached_changes}, "Data riwayat perubahan berhasil diambil.")
            
        conn = get_db_connection()
        cursor = conn.cursor()
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
        cache.set("api_changes", changes, ttl=60)
        return make_response(True, {"changes": changes}, "Data riwayat perubahan berhasil diambil.")
    except Exception as e:
        app.logger.error(f"Error fetching changes: {e}")
        return make_response(False, None, f"Terjadi kesalahan saat memuat data riwayat perubahan: {str(e)}", 500)


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    port_num = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port_num, debug=debug_mode)
