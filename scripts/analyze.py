"""
analyze.py -- Compute WoW deltas, format numbers, build display-ready data.
Reads data/{site_id}_raw.json, writes data/{site_id}_analyzed.json.
Also writes data/overview_analyzed.json for the summary page.
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

DATA_DIR = Path("data")
CONFIG_PATH = Path("config/sites.json")
sites = json.loads(CONFIG_PATH.read_text())["sites"]

def fmt_num(n):
    if n is None:
        return "--"
    return f"{int(n):,}"

def fmt_pct(current, prior):
    if not prior or prior == 0:
        return {"value": None, "display": "--", "direction": "flat", "css": "trend-flat"}
    delta = ((current - prior) / prior) * 100
    direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
    css = f"trend-{direction}"
    sign = "+" if delta > 0 else ""
    return {"value": round(delta, 1), "display": f"{sign}{delta:.1f}%", "direction": direction, "css": css}

def pct_of_total(value, total):
    if not total:
        return 0
    return round((value / total) * 100, 1)

def fmt_seconds(seconds):
    try:
        total = int(round(float(seconds)))
    except Exception:
        return "--"
    if total < 0:
        total = 0
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"

def normalize_audience_label(label):
    raw = (label or "").strip().lower()
    if raw.startswith("new"):
        return "New"
    if "returning" in raw:
        return "Returning"
    if raw in {"", "(not set)", "not set"}:
        return "Unspecified"
    return label

def format_ga_date(date_key):
    try:
        dt = datetime.strptime(str(date_key), "%Y%m%d")
        return dt.strftime("%b %d")
    except Exception:
        return str(date_key)

def evaluate_momentum_signal(wow_value):
    if wow_value is None:
        return {"label": "unknown", "css": "trend-flat", "message": "Insufficient baseline"}
    if wow_value <= -10:
        return {"label": "declining", "css": "trend-down", "message": "Sessions trend: declining"}
    if wow_value < 0:
        return {"label": "softening", "css": "trend-flat", "message": "Sessions trend: slightly down"}
    return {"label": "stable_or_growing", "css": "trend-up", "message": "Sessions trend: stable or up"}

def compute_intent_metrics(top_pages_raw, intent_keywords):
    keywords = [str(k).strip().lower() for k in intent_keywords if str(k).strip()]
    total_top_page_views = sum(int(p.get("value", 0) or 0) for p in top_pages_raw)

    intent_views = 0
    matches = []
    for p in top_pages_raw:
        path = str(p.get("dimension", ""))
        views = int(p.get("value", 0) or 0)
        if not keywords:
            continue
        if any(keyword in path.lower() for keyword in keywords):
            intent_views += views
            matches.append({
                "path": path,
                "views": views,
                "views_fmt": fmt_num(views)
            })

    matches.sort(key=lambda m: m["views"], reverse=True)
    return {
        "views_7d": intent_views,
        "views_7d_fmt": fmt_num(intent_views),
        "top_pages_share_pct": pct_of_total(intent_views, total_top_page_views),
        "top_pages_share_display": f"{pct_of_total(intent_views, total_top_page_views)}%",
        "matched_pages": matches[:5]
    }

def primary_channel(sources_display):
    if not sources_display:
        return {"label": "--", "sessions": 0, "sessions_fmt": "0", "pct": 0}
    top = max(sources_display, key=lambda s: s["sessions"])
    return {
        "label": top["label"],
        "sessions": top["sessions"],
        "sessions_fmt": top["sessions_fmt"],
        "pct": top["pct"]
    }

overview_rows = []

for site in sites:
    site_id = site["id"]
    raw_path = DATA_DIR / f"{site_id}_raw.json"

    if not raw_path.exists():
        raw = {"status": "unavailable", "reason": "raw_file_missing"}
    else:
        raw = json.loads(raw_path.read_text())

    if raw.get("status") != "ok":
        analyzed = {
            "status": "unavailable",
            "reason": raw.get("reason", "unknown"),
            "site_id": site_id,
            "site": site,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        (DATA_DIR / f"{site_id}_analyzed.json").write_text(json.dumps(analyzed, indent=2))
        overview_rows.append({"site": site, "status": "unavailable", "reason": analyzed["reason"]})
        print(f"  [{site_id}] unavailable -- {analyzed['reason']}")
        continue

    core = raw["core"]
    c7  = core["current_7d"]
    p7  = core["prior_7d"]
    r28 = core["rolling_28d"]

    sessions_wow    = fmt_pct(c7["sessions"], p7["sessions"])
    users_wow       = fmt_pct(c7["activeUsers"], p7["activeUsers"])
    pageviews_wow   = fmt_pct(c7["screenPageViews"], p7["screenPageViews"])

    # Device totals for percentages
    device_total = sum(d["value"] for d in raw["devices"])
    sources_total = sum(s["value"] for s in raw["sources"])

    devices_display = [
        {
            "label": d["dimension"].title(),
            "sessions": d["value"],
            "pct": pct_of_total(d["value"], device_total)
        }
        for d in raw["devices"]
    ]

    sources_display = [
        {
            "label": s["dimension"],
            "sessions": s["value"],
            "sessions_fmt": fmt_num(s["value"]),
            "pct": pct_of_total(s["value"], sources_total)
        }
        for s in raw["sources"]
    ]

    intent_keywords = site.get("intent_path_keywords", [])
    intent_metrics = compute_intent_metrics(raw.get("top_pages", []), intent_keywords)
    channel_primary = primary_channel(sources_display)
    momentum_signal = evaluate_momentum_signal(sessions_wow["value"])

    engagement_raw = raw.get("engagement_7d", {}) or {}
    engagement_rate = float(engagement_raw.get("engagementRate", 0.0) or 0.0)
    # GA may return engagementRate as fraction (0-1).
    engagement_rate_pct = engagement_rate * 100 if engagement_rate <= 1 else engagement_rate
    avg_session_duration_sec = float(engagement_raw.get("averageSessionDuration", 0.0) or 0.0)
    engaged_sessions_raw = int(engagement_raw.get("engagedSessions", 0) or 0)
    pageviews_per_session = round((c7["screenPageViews"] / c7["sessions"]), 2) if c7["sessions"] else 0.0

    landing_raw = raw.get("landing_pages", [])
    landing_total = sum(int(p.get("value", 0) or 0) for p in landing_raw)
    landing_display = [
        {
            "path": p.get("dimension", ""),
            "sessions": int(p.get("value", 0) or 0),
            "sessions_fmt": fmt_num(int(p.get("value", 0) or 0)),
            "pct": pct_of_total(int(p.get("value", 0) or 0), landing_total)
        }
        for p in landing_raw
    ]

    countries_raw = raw.get("countries", [])
    countries_total = sum(int(c.get("value", 0) or 0) for c in countries_raw)
    countries_display = [
        {
            "country": c.get("dimension", ""),
            "sessions": int(c.get("value", 0) or 0),
            "sessions_fmt": fmt_num(int(c.get("value", 0) or 0)),
            "pct": pct_of_total(int(c.get("value", 0) or 0), countries_total)
        }
        for c in countries_raw
    ]

    audience_raw = raw.get("new_vs_returning", [])
    audience_total_users = sum(int(a.get("activeUsers", 0) or 0) for a in audience_raw)
    audience_mix = [
        {
            "segment": normalize_audience_label(a.get("dimension", "")),
            "users": int(a.get("activeUsers", 0) or 0),
            "users_fmt": fmt_num(int(a.get("activeUsers", 0) or 0)),
            "sessions": int(a.get("sessions", 0) or 0),
            "sessions_fmt": fmt_num(int(a.get("sessions", 0) or 0)),
            "users_pct": pct_of_total(int(a.get("activeUsers", 0) or 0), audience_total_users)
        }
        for a in audience_raw
    ]
    audience_index = {a["segment"]: a for a in audience_mix}
    new_users_pct = audience_index.get("New", {}).get("users_pct")
    returning_users_pct = audience_index.get("Returning", {}).get("users_pct")
    new_users_pct_display = f"{new_users_pct}%" if new_users_pct is not None else "--"
    returning_users_pct_display = f"{returning_users_pct}%" if returning_users_pct is not None else "--"

    trend_raw = raw.get("daily_trend", [])
    trend_rows = []
    for t in sorted(trend_raw, key=lambda row: str(row.get("dimension", ""))):
        date_key = str(t.get("dimension", ""))
        sessions = int(t.get("sessions", 0) or 0)
        users = int(t.get("activeUsers", 0) or 0)
        pageviews = int(t.get("screenPageViews", 0) or 0)
        trend_rows.append({
            "date_key": date_key,
            "date_label": format_ga_date(date_key),
            "sessions": sessions,
            "sessions_fmt": fmt_num(sessions),
            "users": users,
            "users_fmt": fmt_num(users),
            "pageviews": pageviews,
            "pageviews_fmt": fmt_num(pageviews)
        })

    trend_last_7 = sum(t["sessions"] for t in trend_rows[-7:]) if trend_rows else 0
    trend_prev_7 = sum(t["sessions"] for t in trend_rows[-14:-7]) if len(trend_rows) >= 14 else 0
    trend_wow = fmt_pct(trend_last_7, trend_prev_7) if len(trend_rows) >= 14 else {"value": None, "display": "--", "direction": "flat", "css": "trend-flat"}

    analyzed = {
        "status": "ok",
        "site_id": site_id,
        "site": site,
        "generated_at": raw["generated_at"],
        "kpis": {
            "sessions_7d":   {"raw": c7["sessions"],           "display": fmt_num(c7["sessions"]),          "wow": sessions_wow},
            "users_7d":      {"raw": c7["activeUsers"],        "display": fmt_num(c7["activeUsers"]),       "wow": users_wow},
            "pageviews_7d":  {"raw": c7["screenPageViews"],    "display": fmt_num(c7["screenPageViews"]),   "wow": pageviews_wow},
            "sessions_28d":  {"raw": r28["sessions"],          "display": fmt_num(r28["sessions"])},
            "users_28d":     {"raw": r28["activeUsers"],       "display": fmt_num(r28["activeUsers"])},
            "pageviews_28d": {"raw": r28["screenPageViews"],   "display": fmt_num(r28["screenPageViews"])},
        },
        "top_pages": [
            {"path": p["dimension"], "views": p["value"], "views_fmt": fmt_num(p["value"])}
            for p in raw["top_pages"]
        ],
        "sources":  sources_display,
        "devices":  devices_display,
        "commercial": {
            "revenue_role": site.get("revenue_role", ""),
            "value_signals": site.get("value_signals", site.get("value_actions", [])),
            "primary_channel": channel_primary,
            "intent": intent_metrics,
            "momentum_signal": momentum_signal
        },
        "engagement": {
            "engagement_rate_pct": round(engagement_rate_pct, 1),
            "engagement_rate_display": f"{engagement_rate_pct:.1f}%",
            "avg_session_duration_sec": round(avg_session_duration_sec, 1),
            "avg_session_duration_display": fmt_seconds(avg_session_duration_sec),
            "engaged_sessions_7d": {"raw": engaged_sessions_raw, "display": fmt_num(engaged_sessions_raw)},
            "pageviews_per_session": {"raw": pageviews_per_session, "display": f"{pageviews_per_session:.2f}"},
        },
        "navigation": {
            "landing_pages": landing_display,
            "countries": countries_display,
            "audience_mix": audience_mix,
            "audience_summary": {
                "new_users_pct": new_users_pct,
                "new_users_pct_display": new_users_pct_display,
                "returning_users_pct": returning_users_pct,
                "returning_users_pct_display": returning_users_pct_display
            },
            "daily_trend": trend_rows,
            "trend_summary": {
                "sessions_last_7d": {"raw": trend_last_7, "display": fmt_num(trend_last_7)},
                "sessions_prev_7d": {"raw": trend_prev_7, "display": fmt_num(trend_prev_7)} if trend_prev_7 else {"raw": trend_prev_7, "display": "--"},
                "wow": trend_wow
            }
        }
    }

    (DATA_DIR / f"{site_id}_analyzed.json").write_text(json.dumps(analyzed, indent=2))
    print(f"  [{site_id}] OK -- sessions 7d: {fmt_num(c7['sessions'])} ({sessions_wow['display']} WoW)")

    overview_rows.append({
        "site": site,
        "status": "ok",
        "sessions_7d": {"raw": c7["sessions"], "display": fmt_num(c7["sessions"]), "wow": sessions_wow},
        "users_7d":    {"raw": c7["activeUsers"], "display": fmt_num(c7["activeUsers"])},
        "pageviews_7d":{"raw": c7["screenPageViews"], "display": fmt_num(c7["screenPageViews"])},
        "sessions_28d":{"raw": r28["sessions"], "display": fmt_num(r28["sessions"])},
        "sessions_prior_7d": {"raw": p7["sessions"], "display": fmt_num(p7["sessions"])},
        "engagement": {
            "engagement_rate_pct": round(engagement_rate_pct, 1),
            "engagement_rate_display": f"{engagement_rate_pct:.1f}%",
            "avg_session_duration_display": fmt_seconds(avg_session_duration_sec),
            "pageviews_per_session_display": f"{pageviews_per_session:.2f}"
        },
        "navigation": {
            "audience_summary": {
                "new_users_pct": new_users_pct,
                "new_users_pct_display": new_users_pct_display,
                "returning_users_pct": returning_users_pct,
                "returning_users_pct_display": returning_users_pct_display
            },
            "trend_summary": {
                "sessions_last_7d": {"raw": trend_last_7, "display": fmt_num(trend_last_7)},
                "sessions_prev_7d": {"raw": trend_prev_7, "display": fmt_num(trend_prev_7)} if trend_prev_7 else {"raw": trend_prev_7, "display": "--"},
                "wow": trend_wow
            }
        },
        "commercial": {
            "revenue_role": site.get("revenue_role", ""),
            "primary_channel": channel_primary,
            "intent": intent_metrics,
            "momentum_signal": momentum_signal
        }
    })

overview = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "sites": overview_rows
}
(DATA_DIR / "overview_analyzed.json").write_text(json.dumps(overview, indent=2))

print("analyze.py done.")
