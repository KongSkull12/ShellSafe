# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two roles share one sign-in form; the account's stored role decides where they land (no role picker).

- **System administrator** — runs the ShellSafe node: watches live readings, manages alerts, SMS recipients, sensor thresholds, devices and reports.
- **Authority personnel** — coastal / fisheries officials who check bloom risk and alerts and decide whether to act. Read-mostly.

## Product Purpose

ShellSafe monitors coastal water near shellfish areas with an ESP32 T-Call A7670 node (temperature, pH, turbidity, ORP, EC, GPS) and turns the readings into a harmful-algal-bloom risk level, in-app alerts and SMS alerts. Success: anyone looking at the screen can tell within seconds whether the device is live, which probes are reading, and whether the water is in a risky state.

## Operating Context

- Firmware PUTs a single snapshot to Firebase RTDB `/device_data` every ~5 s; there is no stored history yet.
- Flask server streams the snapshot to browsers over SSE (`/api/sensor-stream`) with polling fallback (`/api/sensor-data`).
- A probe can be physically unplugged (firmware sends `"Disconnected"`), and the whole device can go silent (power, Wi-Fi). These are distinct states and must read differently.
- Used on laptops by the admin and (inferred, unconfirmed) on phones by authority personnel.

## Capabilities and Constraints

- Stack: Flask + Jinja templates, Bootstrap 5 JS (modals, offcanvas, tabs), Chart.js, Leaflet. No build step.
- Thresholds are configurable per sensor (Normal / Warning / Alert bands) at `/threshold_config`.
- SMS: up to 4 recipients in `/sms_config`, test send via `/sms_test`.
- Reports and data-history export buttons exist but export is not implemented.

## Brand Commitments

- Name: ShellSafe. Logo assets: `app/static/img/logo.png`, `app/static/img/NAVLOGO.png`.
- User chose a full new visual look for the logged-in app (2026-10-21).
- Standing preference (2026-10-21): the app must look like a professional SaaS console (Stripe, Linear, Vercel dashboards) and must not read as AI-generated. Played straight: neutral surfaces, hairline borders, one blue accent, restrained motion.
- Each sensor gets its own trend chart; never combine sensors behind tabs.

## Evidence on Hand

- Live data only. No historical readings are stored; history views must not fabricate sample data.

## Product Principles

1. Never show stale data as live. Device offline, probe disconnected, and live reading are three different states.
2. Risk is only stated when there is live data to support it.
3. The current state should be readable at a glance, on a phone in daylight.
4. Admin tools stay plain and predictable; the monitoring view carries the identity.
