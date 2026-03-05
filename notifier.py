"""Standalone scheduled notification sender for the Pushover notifier.

This script can be executed by external schedulers (e.g. cron) to send
notifications without running the Flask web service. It reads the
current ``enabled`` and ``mode`` values from the SQLite database and
decides whether a notification should be sent based on the current
minute. If a message is due, it sends it via Pushover using the
configured user and application tokens.

You do not need to use this script if you are running the Flask
application, as the application itself includes a background scheduler.
However, it remains available for environments where external cron
jobs are preferred.

Environment variables:
    PUSHOVER_USER (str): Your personal Pushover user key. Required.
    PUSHOVER_TOKEN (str): Your Pushover application token. Required.
    APP_DB (str, optional): Path to the SQLite database file. Defaults
        to ``./app.db``.

Usage:
    python3 notifier.py

"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

import requests


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger(__name__)


def get_env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


PUSHOVER_USER: str = get_env_str("PUSHOVER_USER")
PUSHOVER_TOKEN: str = get_env_str("PUSHOVER_TOKEN")
APP_DB: str = get_env_str("APP_DB", "./app.db")


def init_db() -> None:
    """Initialise the SQLite database and ensure a settings row exists.

    Creates the ``settings`` table if necessary and inserts a default
    row with id=1 if no row exists. This function is idempotent and
    safe to call multiple times.
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
                id      INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL,
                mode    TEXT NOT NULL
            );
            """
        )
        # Add mode column if missing
        cursor.execute("PRAGMA table_info(settings);")
        cols = [row[1] for row in cursor.fetchall()]
        if "mode" not in cols:
            cursor.execute(
                "ALTER TABLE settings ADD COLUMN mode TEXT NOT NULL DEFAULT 'pomo'"
            )
        # Ensure row exists
        cursor.execute("SELECT COUNT(*) FROM settings WHERE id=1")
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute(
                "INSERT INTO settings (id, enabled, mode) VALUES (1, 0, 'pomo')"
            )
        conn.commit()


def get_setting() -> Optional[tuple[int, str]]:
    """Fetch the enabled flag and mode from the database.

    Returns:
        A tuple (enabled, mode) or None if the row is missing.
    """
    try:
        with sqlite3.connect(APP_DB) as conn:
            cur = conn.execute("SELECT enabled, mode FROM settings WHERE id=1")
            row = cur.fetchone()
            return (int(row[0]), row[1]) if row else None
    except Exception:
        logger.exception("Failed to read settings from %s", APP_DB)
        return None


def send_pushover(message: str) -> None:
    """Send a Pushover notification."""
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        logger.error("Missing PUSHOVER_USER or PUSHOVER_TOKEN; cannot send message")
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
            logger.error("Pushover status=%s body=%s", resp.status_code, resp.text)
    except Exception:
        logger.exception("Exception while sending Pushover message")


def main() -> None:
    """Entry point for the standalone notifier."""
    # Ensure the database exists and contains a settings row.
    init_db()
    setting = get_setting()
    if setting is None:
        logger.error("No settings row found; did you initialise the database?")
        return
    enabled, mode = setting
    if not enabled:
        logger.info("Notifications disabled; exiting.")
        return
    now = datetime.now(timezone.utc)
    # Convert to JST manually (UTC+9)
    hh = (now.hour + 9) % 24
    mm = now.minute
    hhmm = f"{hh:02d}:{mm:02d}"
    message: Optional[str] = None
    if mode == "pomo":
        if mm in (0, 30):
            message = f"{hhmm} 作業開始"
        elif mm in (25, 55):
            message = f"{hhmm} 休憩開始"
    elif mode == "quarter":
        if mm in (0, 15, 30, 45):
            message = f"{hhmm}の通知です"
    if message:
        logger.info("Sending notification: %s", message)
        send_pushover(message)
    else:
        logger.info("No notification due at this minute (mode=%s)", mode)


if __name__ == "__main__":
    main()