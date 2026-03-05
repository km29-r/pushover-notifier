# Pushover Notifier Service

This repository contains a lightweight Python service for sending
scheduled notifications via [Pushover](https://pushover.net). It is
designed to run on a always‑on platform such as Render and can be
controlled remotely via simple HTTP endpoints or a standalone cron
script. Notifications are delivered to your iPhone and Apple Watch
through the Pushover app.

## Overview

The service consists of two parts:

1. **Flask web application (`app.py`)** – Exposes endpoints to start
   and stop notifications, switch between two scheduling modes, query
   the current state, and send test messages. It maintains a small
   SQLite database holding a single settings row with an ``enabled``
   flag and a ``mode`` string. A background scheduler runs inside
   the application to dispatch messages at the appropriate times.
2. **Standalone notifier script (`notifier.py`)** – Optionally used
   with external schedulers such as cron. It reads the same
   database and determines whether a message should be sent based on
   the current time and mode.

You can choose to run only the Flask application (which includes a
background scheduler) or to drive notifications via cron using
``notifier.py``. Both approaches honour the same settings.

## Scheduling modes

Two scheduling patterns are supported:

| Mode      | Minutes past the hour | Message                                    |
|----------|-----------------------|---------------------------------------------|
| ``pomo`` | 00, 30               | "HH:MM 作業開始" (start work)             |
|          | 25, 55               | "HH:MM 休憩開始" (start break)            |
| ``quarter`` | 00, 15, 30, 45      | "HH:MMの通知です" (generic notification) |

Times are computed in the Asia/Tokyo time zone (UTC+9). When the
service sends a message, ``HH:MM`` is formatted in that time zone.

## Endpoints

All state‑changing endpoints require a secret key passed as a query
parameter named ``key``. Set the ``CONTROL_KEY`` environment
variable to a long, random string and include ``?key=your_key`` on
requests to the following paths:

| Method & Path        | Description                                   |
|----------------------|-----------------------------------------------|
| `GET /start`         | Enable notifications and resume the UptimeRobot monitor (if configured). Returns `started`. |
| `GET /stop`          | Disable notifications and pause the monitor. Returns `stopped`. |
| `GET /mode/pomo`     | Switch to Pomodoro mode. Returns `mode=pomo`.  |
| `GET /mode/quarter`  | Switch to quarter‑hour mode. Returns `mode=quarter`. |
| `GET /test`          | Immediately send a notification according to the current mode (ignores time). Returns `sent`. |

Endpoints that do **not** require a key:

| Method & Path   | Description                                        |
|-----------------|----------------------------------------------------|
| `GET /status`   | Returns a JSON object with `enabled` and `mode`.   |
| `GET /ping`     | Health check used by UptimeRobot. Returns `ok`.    |

## Environment variables

All configuration is performed via environment variables. Copy
`.env.example` to `.env` and fill in the values:

- `PUSHOVER_USER` – **Required.** Your personal Pushover user key.
- `PUSHOVER_TOKEN` – **Required.** The application token created in
  your Pushover dashboard.
- `CONTROL_KEY` – **Required.** A secret string to protect the
  control endpoints. Choose something long and random.
- `UPTIMEROBOT_API_KEY` – Optional. If set along with
  `UPTIMEROBOT_MONITOR_ID`, the service will automatically resume
  or pause the specified monitor when notifications are enabled or
  disabled. See [UptimeRobot API](https://uptimerobot.com/api). The
  monitor should be configured to call the `/ping` endpoint.
- `UPTIMEROBOT_MONITOR_ID` – Optional. The ID of the monitor to
  control when start/stop endpoints are called.
- `APP_DB` – Optional. Path to the SQLite database file. Defaults
  to `./app.db`.
- `PORT` – Optional. Port for the Flask server to listen on.

## Running the service

1. **Install dependencies.** Create a virtual environment and install
   the required packages:

   ```sh
   python3 -m venv venv
   . venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Create a `.env` file.** Copy `.env.example` to `.env` and set
   the required variables (`PUSHOVER_USER`, `PUSHOVER_TOKEN`,
   `CONTROL_KEY`, and optionally the UptimeRobot keys).

3. **Run the Flask application.** Make sure your environment
   variables are loaded and start the server:

   ```sh
   export $(grep -v '^#' .env | xargs)
   python app.py
   ```

   The database will be created automatically if it does not
   already exist, and a background scheduler will begin checking
   whether notifications should be sent.

4. **Configure UptimeRobot (optional).**

   - Create a new monitor of type **HTTP(s)** pointing to your
     `/ping` endpoint (e.g. `https://your-app.onrender.com/ping`). Set
     the monitoring interval to 5 minutes (free plan) or 1 minute
     (paid).
   - Note the monitor ID and set it in `UPTIMEROBOT_MONITOR_ID`.
   - Obtain your UptimeRobot API key from your account settings and
     set it in `UPTIMEROBOT_API_KEY`.
   - When you call `/start?key=...`, the monitor will be resumed. When
     you call `/stop?key=...`, the monitor will be paused. Pausing
     the monitor prevents unnecessary pings and allows your service to
     spin down on platforms that idle inactive services.

5. **Create iOS shortcuts (optional).**

   To simplify operations from your iPhone or Apple Watch, create
   shortcuts that open the following URLs:

   - Start notifications:
     `https://your-app.onrender.com/start?key=YOUR_CONTROL_KEY`
   - Stop notifications:
     `https://your-app.onrender.com/stop?key=YOUR_CONTROL_KEY`
   - Switch to Pomodoro mode:
     `https://your-app.onrender.com/mode/pomo?key=YOUR_CONTROL_KEY`
   - Switch to quarter‑hour mode:
     `https://your-app.onrender.com/mode/quarter?key=YOUR_CONTROL_KEY`

   Use Safari's **Add to Home Screen** feature to place these
   shortcuts on your home screen for one‑tap access.

## Using the standalone script with cron

If you prefer to use cron instead of the internal scheduler, you
can run `notifier.py` at whatever intervals you like. For example,
to mimic the built‑in schedule, add the following to your crontab:

```cron
0,15,25,30,45,55 * * * * cd /path/to/line_notifier && \  
  export $(grep -v '^#' .env | xargs) && \  
  python notifier.py >>/var/log/pushover_notifier.log 2>&1
```

The script will read the current mode and enabled flag from
``app.db`` and send a notification only when appropriate.

## Development and testing

* The code is formatted to be PEP 8 compliant and includes type hints
  where useful.
* Logging is configured to output ISO‑8601 timestamps with the
  process ID for easier correlation of events.
* HTTP requests have timeouts and all errors are logged. Invalid
  UptimeRobot responses are surfaced to the logs.
* When forcing a notification via `/test`, the service always
  falls back to a generic message if the current time is not one of
  the scheduled minutes.

## License

This project is provided as‑is under the MIT License. Feel free to
adapt it for your personal or commercial use.