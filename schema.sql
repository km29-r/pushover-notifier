-- Schema for the Pushover notifier service
--
-- The settings table stores a single row (id=1) to control
-- notifications. The ``enabled`` column determines whether
-- scheduled notifications are active. The ``mode`` column holds
-- either 'pomo' or 'quarter' to indicate which schedule pattern
-- should be applied. Additional rows are not used.

CREATE TABLE IF NOT EXISTS settings (
    id      INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL,
    mode    TEXT NOT NULL
);