"""Constants for the Gemstone Lights integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "gemstone"
MANUFACTURER = "Gemstone Lights"
MODEL = "Permanent Light Controller"

PLATFORMS: list[str] = ["light", "select", "sensor"]

CONF_EMAIL = "email"
CONF_PASSWORD = "password"  # noqa: S105 - field name, not a value

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
