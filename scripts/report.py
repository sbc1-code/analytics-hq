"""
report.py -- Render Jinja2 templates and write public/ directory tree.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader

DATA_DIR   = Path("data")
PUBLIC_DIR = Path("public")
ASSETS_DIR = Path("assets")
PUBLIC_DIR.mkdir(exist_ok=True)

CONFIG_PATH = Path("config/sites.json")
sites = json.loads(CONFIG_PATH.read_text())["sites"]

env = Environment(loader=FileSystemLoader("templates"), autoescape=True)

generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

def fmt_num(n):
    return f"{int(n):,}"

def fmt_pct(current, prior):
    if not prior:
        return {"value": None, "display": "--", "css": "trend-flat"}
    delta = ((current - prior) / prior) * 100
    css = "trend-up" if delta > 0 else ("trend-down" if delta < 0 else "trend-flat")
    sign = "+" if delta > 0 else ""
    return {"value": round(delta, 1), "display": f"{sign}{delta:.1f}%", "css": css}

def avg(values):
    if not values:
        return None
    return round(sum(values) / len(values), 1)

def compute_executive_summary(overview_rows):
    ok_rows = [r for r in overview_rows if r.get("status") == "ok"]
    if not ok_rows:
        return {
            "sites_reporting": 0,
            "total_sessions_7d": {"raw": 0, "display": "--"},
            "total_users_7d": {"raw": 0, "display": "--"},
            "total_pageviews_7d": {"raw": 0, "display": "--"},
            "total_sessions_wow": {"value": None, "display": "--", "css": "trend-flat"},
            "total_intent_views_7d": {"raw": 0, "display": "--"},
            "avg_engagement_rate": {"value": None, "display": "--"},
            "cross_site_pages_per_session": {"value": None, "display": "--"},
            "avg_new_users_share": {"value": None, "display": "--"},
            "top_upside": None,
            "top_risk": None
        }

    total_sessions = sum(r.get("sessions_7d", {}).get("raw", 0) for r in ok_rows)
    total_users = sum(r.get("users_7d", {}).get("raw", 0) for r in ok_rows)
    total_pageviews = sum(r.get("pageviews_7d", {}).get("raw", 0) for r in ok_rows)
    total_prior_sessions = sum(r.get("sessions_prior_7d", {}).get("raw", 0) for r in ok_rows)
    total_intent_views = sum(
        r.get("commercial", {}).get("intent", {}).get("views_7d", 0)
        for r in ok_rows
    )
    engagement_rates = [
        float(r.get("engagement", {}).get("engagement_rate_pct"))
        for r in ok_rows
        if r.get("engagement", {}).get("engagement_rate_pct") is not None
    ]
    new_user_shares = [
        float(r.get("navigation", {}).get("audience_summary", {}).get("new_users_pct"))
        for r in ok_rows
        if r.get("navigation", {}).get("audience_summary", {}).get("new_users_pct") is not None
    ]
    pages_per_session = round((total_pageviews / total_sessions), 2) if total_sessions else None

    trend_candidates = []
    for r in ok_rows:
        wow = r.get("sessions_7d", {}).get("wow", {})
        trend_candidates.append({
            "site_name": r.get("site", {}).get("name", "Unknown"),
            "display": wow.get("display", "--"),
            "value": wow.get("value"),
            "css": wow.get("css", "trend-flat")
        })
    trend_candidates = [c for c in trend_candidates if c["value"] is not None]

    top_upside = max(trend_candidates, key=lambda c: c["value"]) if trend_candidates else None
    top_risk = min(trend_candidates, key=lambda c: c["value"]) if trend_candidates else None

    return {
        "sites_reporting": len(ok_rows),
        "total_sessions_7d": {"raw": total_sessions, "display": fmt_num(total_sessions)},
        "total_users_7d": {"raw": total_users, "display": fmt_num(total_users)},
        "total_pageviews_7d": {"raw": total_pageviews, "display": fmt_num(total_pageviews)},
        "total_sessions_wow": fmt_pct(total_sessions, total_prior_sessions),
        "total_intent_views_7d": {"raw": total_intent_views, "display": fmt_num(total_intent_views)},
        "avg_engagement_rate": {
            "value": avg(engagement_rates),
            "display": f"{avg(engagement_rates):.1f}%" if avg(engagement_rates) is not None else "--"
        },
        "cross_site_pages_per_session": {
            "value": pages_per_session,
            "display": f"{pages_per_session:.2f}" if pages_per_session is not None else "--"
        },
        "avg_new_users_share": {
            "value": avg(new_user_shares),
            "display": f"{avg(new_user_shares):.1f}%" if avg(new_user_shares) is not None else "--"
        },
        "top_upside": top_upside,
        "top_risk": top_risk
    }

# Load alerts
alerts_path = DATA_DIR / "alerts.json"
alerts = json.loads(alerts_path.read_text()) if alerts_path.exists() else {"has_alerts": False, "alerts": []}

# Load overview data
overview_path = DATA_DIR / "overview_analyzed.json"
overview = json.loads(overview_path.read_text()) if overview_path.exists() else {"sites": []}
executive_summary = compute_executive_summary(overview.get("sites", []))

# Load per-site analyzed data
sites_data = []
for site in sites:
    site_id = site["id"]
    path = DATA_DIR / f"{site_id}_analyzed.json"
    if path.exists():
        sites_data.append(json.loads(path.read_text()))
    else:
        sites_data.append({
            "status": "unavailable",
            "reason": "file_not_found",
            "site_id": site_id,
            "site": site
        })

# Copy static assets
if ASSETS_DIR.exists():
    public_assets = PUBLIC_DIR / "assets"
    shutil.copytree(ASSETS_DIR, public_assets, dirs_exist_ok=True)
    print("  Copied public/assets/")

# Render overview page
overview_html = env.get_template("overview.html").render(
    overview=overview,
    sites_data=sites_data,
    executive_summary=executive_summary,
    alerts=alerts,
    generated_at=generated_at,
    root_prefix="."
)
(PUBLIC_DIR / "index.html").write_text(overview_html, encoding="utf-8")
print("  Wrote public/index.html")

# Render per-site pages
for site_data in sites_data:
    site_id = site_data.get("site_id") or site_data.get("site", {}).get("id")
    site_dir = PUBLIC_DIR / site_id
    site_dir.mkdir(exist_ok=True)

    site_alerts = [a for a in alerts.get("alerts", []) if a["site_id"] == site_id]

    site_html = env.get_template("site.html").render(
        data=site_data,
        site_alerts=site_alerts,
        generated_at=generated_at,
        root_prefix=".."
    )
    (site_dir / "index.html").write_text(site_html, encoding="utf-8")
    print(f"  Wrote public/{site_id}/index.html")

print("report.py done.")
