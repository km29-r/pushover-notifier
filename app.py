<<<<<<< HEAD
"""Webhook and scheduler service for Pushover-based notifier.

This Flask application exposes endpoints to control a simple
notification service. It maintains a small SQLite database
containing a single settings row with two flags: whether the
notification schedule is enabled and which schedule mode to use.

There are two supported schedule modes:

* ``pomo`` – Implements a Pomodoro-like cycle. At minutes 00 and 30
  past the hour it sends a "作業開始" (work start) notification. At
  minutes 25 and 55 past the hour it sends a "休憩開始" (break
  start) notification. Only these four minute values trigger
  notifications.
* ``quarter`` – Sends a generic time notification at each quarter
  hour: 00, 15, 30 and 45 minutes past the hour. The message
  contains the current time in HH:MM format followed by ``の通知です``.

Clients interact with this service via simple HTTP GET requests. All
state-changing endpoints require a ``key`` query parameter whose
value must match the ``CONTROL_KEY`` environment variable. This
ensures that only authorised callers can enable, disable, or change
the mode.

Environment variables:

* ``PUSHOVER_USER`` – Your personal Pushover user key. Required.
* ``PUSHOVER_TOKEN`` – The application token generated when you
  registered your Pushover application. Required.
* ``CONTROL_KEY`` – A secret used to authorise requests to
  state‑changing endpoints. Required for security.
* ``UPTIMEROBOT_API_KEY`` – Optional API key for the UptimeRobot
  account. If set along with ``UPTIMEROBOT_MONITOR_ID``, the
  application will automatically resume or pause the specified
  monitor when the notifier is started or stopped, respectively.
* ``UPTIMEROBOT_MONITOR_ID`` – Optional monitor ID to control when
  starting or stopping the notifier. Requires ``UPTIMEROBOT_API_KEY``.
* ``APP_DB`` – Optional path to the SQLite database file. Defaults
  to ``./app.db``. The database file is created automatically if
  missing.
* ``PORT`` – Optional port on which to run the Flask server.
  Defaults to ``8080``.

The service exposes the following endpoints:

* ``GET /start?key=...`` – Enable notifications and resume the
  UptimeRobot monitor (if configured). Returns ``started`` on
  success.
* ``GET /stop?key=...`` – Disable notifications and pause the
  UptimeRobot monitor (if configured). Returns ``stopped`` on
  success.
* ``GET /mode/pomo?key=...`` – Switch to Pomodoro mode. Returns
  ``mode=pomo`` on success.
* ``GET /mode/quarter?key=...`` – Switch to quarter‑hour mode.
  Returns ``mode=quarter`` on success.
* ``GET /status`` – Return a JSON object describing the current
  ``enabled`` state and ``mode``. Does not require a key.
* ``GET /ping`` – Simple health check endpoint used by UptimeRobot
  to keep the service awake. Returns ``ok``.
* ``GET /test?key=...`` – Immediately trigger a notification using
  the current mode, regardless of the time. Useful for manual
  testing. Returns ``sent``.

Internally, the application runs a background scheduler (via
APScheduler) that calls ``send_notification`` at specific minute
intervals. The scheduler is configured to run the job at
minutes 00, 15, 25, 30, 45 and 55 past every hour. The job then
decides whether to send a notification based on the current mode.

"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, Response, abort, jsonify, request


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def get_env_str(name: str, default: str = "") -> str:
    """Retrieve a string environment variable with a default."""
    return os.environ.get(name, default)


def get_env_int(name: str, default: int) -> int:
    """Retrieve an integer environment variable with a default."""
    try:
        return int(os.environ.get(name, ""))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Global configuration from environment
# ---------------------------------------------------------------------------

PUSHOVER_USER: str = get_env_str("PUSHOVER_USER")
PUSHOVER_TOKEN: str = get_env_str("PUSHOVER_TOKEN")
CONTROL_KEY: str = get_env_str("CONTROL_KEY")
APP_DB: str = get_env_str("APP_DB", "./app.db")
LISTEN_PORT: int = get_env_int("PORT", 8080)
# UptimeRobot integration
UPTIMEROBOT_API_KEY: str = get_env_str("UPTIMEROBOT_API_KEY")
UPTIMEROBOT_MONITOR_ID: str = get_env_str("UPTIMEROBOT_MONITOR_ID")


# ---------------------------------------------------------------------------
# Database and settings management
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Initialise the SQLite database and ensure a settings row exists.

    Creates a single table ``settings`` with columns ``id`` (INTEGER
    primary key), ``enabled`` (INTEGER) and ``mode`` (TEXT). Ensures
    there is exactly one row with id=1. If an older schema is
    detected, it attempts to add missing columns.
    """
    try:
        os.makedirs(os.path.dirname(APP_DB), exist_ok=True)
    except Exception:
        pass
    with sqlite3.connect(APP_DB) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id     INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL,
                mode   TEXT NOT NULL
            );
            """
        )
        # Check if mode column exists; if not, add it
        cursor.execute(
            "PRAGMA table_info(settings);")
        columns = [row[1] for row in cursor.fetchall()]
        if "mode" not in columns:
            cursor.execute(
                "ALTER TABLE settings ADD COLUMN mode TEXT NOT NULL DEFAULT 'pomo'"
            )
        # Ensure a single row with id=1 exists
        cursor.execute("SELECT COUNT(*) FROM settings WHERE id=1")
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute(
                "INSERT INTO settings (id, enabled, mode) VALUES (1, 0, 'pomo')"
            )
        conn.commit()
    logger.info("Database initialised at %s", APP_DB)


def is_enabled() -> bool:
    """Return True if notifications are enabled."""
    with sqlite3.connect(APP_DB) as conn:
        cur = conn.execute("SELECT enabled FROM settings WHERE id=1")
        row = cur.fetchone()
        return bool(row[0]) if row else False


def get_mode() -> str:
    """Return the current mode (``pomo`` or ``quarter``)."""
    with sqlite3.connect(APP_DB) as conn:
        cur = conn.execute("SELECT mode FROM settings WHERE id=1")
        row = cur.fetchone()
        return row[0] if row else "pomo"


def set_enabled(value: bool) -> None:
    """Set the enabled flag in the settings row."""
    with sqlite3.connect(APP_DB) as conn:
        conn.execute(
            "UPDATE settings SET enabled=? WHERE id=1",
            (1 if value else 0,),
        )
        conn.commit()
    logger.info("Set enabled=%s", value)


def set_mode(mode: str) -> None:
    """Update the mode in the settings row."""
    if mode not in ("pomo", "quarter"):
        raise ValueError("Invalid mode: %s" % mode)
    with sqlite3.connect(APP_DB) as conn:
        conn.execute(
            "UPDATE settings SET mode=? WHERE id=1",
            (mode,),
        )
        conn.commit()
    logger.info("Set mode=%s", mode)


# ---------------------------------------------------------------------------
# UptimeRobot helper functions
# ---------------------------------------------------------------------------


def uptimerobot_request(status: int) -> None:
    """Send a request to UptimeRobot to resume (1) or pause (0) the monitor.

    Does nothing if the API key or monitor ID are unset. Logs the
    result or any errors. See https://uptimerobot.com/api for
    details.

    Args:
        status: 1 to resume the monitor, 0 to pause it.
    """
    if not UPTIMEROBOT_API_KEY or not UPTIMEROBOT_MONITOR_ID:
        return
    payload = {
        "api_key": UPTIMEROBOT_API_KEY,
        "id": UPTIMEROBOT_MONITOR_ID,
        "status": str(status),
    }
    try:
        resp = requests.post(
            "https://api.uptimerobot.com/v2/editMonitor",
            data=payload,
            timeout=10,
        )
        if not resp.ok:
            logger.error(
                "UptimeRobot API error status=%s body=%s",
                resp.status_code,
                resp.text,
            )
        else:
            data = resp.json()
            if data.get("stat") != "ok":
                logger.error("UptimeRobot API response not ok: %s", data)
    except Exception:
        logger.exception("Failed to call UptimeRobot API")


def resume_monitor() -> None:
    """Resume the UptimeRobot monitor if configured."""
    uptimerobot_request(status=1)


def pause_monitor() -> None:
    """Pause the UptimeRobot monitor if configured."""
    uptimerobot_request(status=0)


# ---------------------------------------------------------------------------
# Pushover notification helper
# ---------------------------------------------------------------------------


def send_pushover(message: str) -> None:
    """Send a Pushover notification.

    Logs HTTP status and response body on error.

    Args:
        message: The message text to send. Title is fixed to ``Pomodoro``.
    """
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        logger.error(
            "PUSHOVER_USER or PUSHOVER_TOKEN not set; cannot send notifications."
        )
        return
    payload = {
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "message": message,
        "title": "Pomodoro",
    }
    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data=payload,
            timeout=10,
        )
        if not resp.ok:
            logger.error(
                "Pushover send failed status=%s body=%s", resp.status_code, resp.text
            )
    except Exception:
        logger.exception("Exception while sending Pushover message")


# ---------------------------------------------------------------------------
# Notification scheduling
# ---------------------------------------------------------------------------


def send_notification(force: bool = False) -> None:
    """Check the current mode and time and send a notification if due.

    If ``force`` is True, a notification will be sent irrespective of
    the enabled flag and without regard to the time. This is useful
    for manual testing via the ``/test`` endpoint. When not forced,
    this function aborts immediately if notifications are disabled.
    """
    if not force and not is_enabled():
        return
    now = datetime.now(timezone.utc)
    # Convert to Asia/Tokyo by adding 9 hours manually (avoid heavy deps)
    jst = now.astimezone(timezone.utc).replace(tzinfo=None)
    # Actually use timezone offset 9; it's simpler to compute local time
    hh = (now.hour + 9) % 24
    mm = now.minute
    hhmm = f"{hh:02d}:{mm:02d}"
    mode = get_mode()
    message: str | None = None
    if mode == "pomo":
        if mm in (0, 30):
            message = f"{hhmm} 作業開始"
        elif mm in (25, 55):
            message = f"{hhmm} 休憩開始"
    elif mode == "quarter":
        if mm in (0, 15, 30, 45):
            message = f"{hhmm}の通知です"
    if message is None:
        if force:
            # When forcing, fall back to generic message
            message = f"{hhmm}の通知です"
        else:
            return
    send_pushover(message)


def setup_scheduler() -> BackgroundScheduler:
    """Create and start the background scheduler.

    Returns the scheduler instance so callers can keep it alive.
    """
    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
    # Cron triggers at 00, 15, 25, 30, 45 and 55 minutes each hour.
    scheduler.add_job(send_notification, "cron", minute="0,15,25,30,45,55")
    scheduler.start()
    return scheduler


# ---------------------------------------------------------------------------
# Flask application setup
# ---------------------------------------------------------------------------

app = Flask(__name__)


def require_key() -> None:
    """Verify that the request's ``key`` parameter matches CONTROL_KEY.

    Aborts with 403 if the key is missing or incorrect. If
    ``CONTROL_KEY`` is empty, all keys are considered invalid and a
    403 is returned.
    """
    if not CONTROL_KEY:
        abort(403)
    k = request.args.get("key", "")
    if k != CONTROL_KEY:
        abort(403)


@app.route("/start")
def start() -> Response:
    """Enable notifications and resume the UptimeRobot monitor."""
    require_key()
    set_enabled(True)
    # Resume monitor if configured
    resume_monitor()
    return Response("started", content_type="text/plain")


@app.route("/stop")
def stop() -> Response:
    """Disable notifications and pause the UptimeRobot monitor."""
    require_key()
    set_enabled(False)
    # Pause monitor if configured
    pause_monitor()
    return Response("stopped", content_type="text/plain")


@app.route("/mode/pomo")
def mode_pomo() -> Response:
    """Switch to Pomodoro mode."""
    require_key()
    set_mode("pomo")
    return Response("mode=pomo", content_type="text/plain")


@app.route("/mode/quarter")
def mode_quarter() -> Response:
    """Switch to quarter-hour mode."""
    require_key()
    set_mode("quarter")
    return Response("mode=quarter", content_type="text/plain")


@app.route("/status")
def status() -> Response:
    """Return a JSON object with the current enabled flag and mode."""
    data = {"enabled": is_enabled(), "mode": get_mode()}
    return jsonify(data)


@app.route("/ping")
def ping() -> Response:
    """Health check endpoint used by UptimeRobot."""
    return Response("ok", content_type="text/plain")


@app.route("/test")
def test() -> Response:
    """Force-send a notification according to the current mode."""
    require_key()
    send_notification(force=True)
    return Response("sent", content_type="text/plain")


def run_server() -> None:
    """Initialise the database, start the scheduler and run the server."""
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        logger.error(
            "PUSHOVER_USER and PUSHOVER_TOKEN must be set for the service to run."
        )
    if not CONTROL_KEY:
        logger.error(
            "CONTROL_KEY must be set; otherwise all protected endpoints will return 403."
        )
    init_db()
    # Start scheduler
    setup_scheduler()
    # Run Flask
    app.run(host="0.0.0.0", port=LISTEN_PORT)


if __name__ == "__main__":
    run_server()
=======
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

>>>>>>> 8552b7f517a658809fe936dc79ccccd889e1935d
