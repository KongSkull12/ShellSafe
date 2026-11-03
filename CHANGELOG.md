# Changelog

The app version lives in `VERSION` and is shown at the bottom of the dashboard
sidebar together with the deployed commit. Bump it with each release, add an
entry here, and tag the commit (`git tag v<version>`).

## Unreleased

- Settings › Firmware: flash the ESP32 over USB from Chrome/Edge (Web Serial + esptool-js), no Arduino IDE needed. App updates keep saved calibration; full install is opt-in.
- `python build_firmware.py` compiles the sketch with arduino-cli into gitignored `firmware/build/`, which the page offers to admins.

## 1.1.0 — 2026-11-02

- Data history reads the per-minute readings the device saves to /readings (up to 24 h), merged with live samples; 15 min / 1 hour zoom by time.
- History parsing accepts millisecond or second timestamps and logs salinity.
- Vercel: remove the empty `pyproject.toml` so dependencies install from `requirements.txt`.
- Version label in the sidebar; CSS/JS cache-busting tied to the deployed version.

## 1.0.0

- Initial ShellSafe release: Flask dashboard, ESP32 firmware, Firebase backend.
