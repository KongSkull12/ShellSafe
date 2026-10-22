---
version: 1
slug: "app-templates-admin-dashboard-html"
primary_target: "app/templates/admin_dashboard.html"
related_targets: ["app/templates/dashboard_base.html","app/templates/authority_dashboard.html","app/templates/devices.html"]
---

# ShellSafe logged-in app

Scope: every logged-in page (admin + authority) plus the single sign-in form. Visitor mode: Operate.
Task: know in seconds whether the node is live, which probes read, and whether water risk is elevated; then manage alerts, SMS recipients, thresholds, reports.
Constraints: Flask/Jinja, no build step; Chart.js, Leaflet, Bootstrap Icons. Never show stale data as live.

## Direction contract

THESIS: The category standard, played straight: a professional SaaS operations console in the register of Stripe, Linear and Vercel dashboards. The user rejected the painted-hull world as looking AI-generated; refuse chunky rounded cards, coloured accent stripes, condensed display caps, eyebrow labels and tinted hero banners.

OWN-WORLD: White surfaces on a near-white canvas, 1px neutral hairlines, 6-8px radii, almost no shadow. One blue accent for actions and chart lines. Geist for all text with tabular numerals. Status shown as a small dot plus word, colour only where it carries meaning.

STORY: Visitor sees the live indicator in the top bar, reads the risk line, scans five readings in one bordered strip, then checks each sensor's own trend chart.

FIRST VIEWPORT: Light sidebar with the ShellSafe wordmark and nav. Top bar with page title and live indicator. Page: risk line, a five-cell metric strip with dividers, then a two-column grid of six panels: five per-sensor trend charts and recent alerts.

FORM: Canon (category standard) chosen by the user over the rolled direction. seed:a579508301ab0924 (original roll, superseded by user choice).

SIGNATURE: Live values change with a digit pop-in; status labels cross-blur; content enters with a short stagger. Restrained, product-grade motion only.
