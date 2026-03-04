from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)

USER_KEY = os.environ.get("PUSHOVER_USER")
APP_TOKEN = os.environ.get("PUSHOVER_TOKEN")

DB = "app.db"

def init_db():
    with sqlite3.connect(DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL
            )
        """)
        conn.execute("INSERT OR IGNORE INTO settings (id, enabled) VALUES (1, 0)")
        conn.commit()

def is_enabled():
    with sqlite3.connect(DB) as conn:
        cur = conn.execute("SELECT enabled FROM settings WHERE id=1")
        return cur.fetchone()[0] == 1

def set_enabled(value: int):
    with sqlite3.connect(DB) as conn:
        conn.execute("UPDATE settings SET enabled=?", (value,))
        conn.commit()

def send_notification():
    if not is_enabled():
        return

    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    msg = f"{now.strftime('%H:%M')}の通知です"

    requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": APP_TOKEN,
            "user": USER_KEY,
            "message": msg
        },
        timeout=10
    )

scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
scheduler.add_job(send_notification, "cron", minute="0,25,30,55")
scheduler.start()

@app.route("/start")
def start():
    set_enabled(1)
    return "started"

@app.route("/stop")
def stop():
    set_enabled(0)
    return "stopped"

@app.route("/")
def index():
    return "running"

@app.route("/test")
def test():
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    msg = f"{now.strftime('%H:%M')}の通知です"

    r = requests.post(
        "https://api.pushover.net/1/messages.json",
        data={"token": APP_TOKEN, "user": USER_KEY, "message": msg},
        timeout=10,
    )

    return {
        "status": r.status_code,
        "body": r.text,
        "message": msg,
    }

@app.route("/debug")
def debug():
    # env の有無と enabled を可視化
    return {
        "enabled": is_enabled(),
        "has_PUSHOVER_USER": bool(USER_KEY),
        "has_PUSHOVER_TOKEN": bool(APP_TOKEN),
    }
    
@app.route("/ping")
def ping():
    return "ok"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=10000)

