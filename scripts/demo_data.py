"""
demo_data.py -- Deterministic sample GA4 data for Analytics HQ demo mode.

When no live GA4 credentials/property IDs are configured, the pipeline renders a
fully populated SAMPLE dashboard instead of an empty setup state, so the project
can be evaluated as a working report. Every figure is synthetic and clearly badged
as "Sample data" in the UI. The moment real GA4 secrets are wired, fetch.py uses
live data and this module is bypassed.

Numbers are deterministic per (site, calendar day) so scheduled runs do not churn:
totals stay stable, only the trailing 14-day date labels roll forward so the report
reads as live.
"""

import hashlib
from datetime import datetime, timezone, timedelta

# Fictional B2B SaaS ("Acme Cloud") across three GA4 properties. Site ids match
# config/sites.json so the live-config path keeps the same env-var mapping.
PROFILES = {
    "primary": {
        "sessions_7d": 14280,
        "wow": 0.082,
        "pages_per_session": 2.4,
        "engagement_rate": 0.571,
        "avg_session_duration": 138.0,
        "new_user_share": 0.68,
        "channels": [
            ("Organic Search", 0.46), ("Direct", 0.22), ("Paid Search", 0.14),
            ("Referral", 0.09), ("Organic Social", 0.06), ("Email", 0.03),
        ],
        "devices": [("desktop", 0.58), ("mobile", 0.38), ("tablet", 0.04)],
        "top_pages": [
            ("/", 0.17), ("/pricing", 0.12), ("/product/platform", 0.10),
            ("/blog/gtm-automation-stack", 0.085), ("/demo", 0.07),
            ("/customers", 0.055), ("/product/integrations", 0.05),
            ("/blog/marketing-attribution", 0.045), ("/contact", 0.035), ("/about", 0.03),
        ],
        "landing_pages": [
            ("/", 0.21), ("/pricing", 0.13), ("/blog/gtm-automation-stack", 0.11),
            ("/demo", 0.08), ("/product/platform", 0.07), ("/blog/marketing-attribution", 0.06),
            ("/customers", 0.05), ("/contact", 0.04),
        ],
        "countries": [
            ("United States", 0.62), ("United Kingdom", 0.09), ("Canada", 0.07),
            ("Germany", 0.05), ("Australia", 0.04), ("India", 0.035), ("Mexico", 0.03),
        ],
    },
    "support": {
        "sessions_7d": 7120,
        "wow": -0.031,
        "pages_per_session": 3.1,
        "engagement_rate": 0.638,
        "avg_session_duration": 196.0,
        "new_user_share": 0.34,
        "channels": [
            ("Organic Search", 0.39), ("Direct", 0.41), ("Referral", 0.12),
            ("Email", 0.05), ("Organic Social", 0.03),
        ],
        "devices": [("desktop", 0.71), ("mobile", 0.26), ("tablet", 0.03)],
        "top_pages": [
            ("/docs/getting-started", 0.16), ("/docs/api/authentication", 0.12),
            ("/docs/integrations/salesforce", 0.10), ("/support", 0.09),
            ("/docs/api/webhooks", 0.08), ("/help/billing", 0.07),
            ("/docs/data-model", 0.06), ("/download/sdk", 0.05),
            ("/knowledge/troubleshooting", 0.045), ("/docs/changelog", 0.04),
        ],
        "landing_pages": [
            ("/docs/getting-started", 0.19), ("/docs/api/authentication", 0.14),
            ("/support", 0.11), ("/docs/integrations/salesforce", 0.09),
            ("/help/billing", 0.07), ("/docs/api/webhooks", 0.06),
            ("/download/sdk", 0.05), ("/knowledge/troubleshooting", 0.04),
        ],
        "countries": [
            ("United States", 0.55), ("India", 0.11), ("United Kingdom", 0.08),
            ("Germany", 0.06), ("Canada", 0.05), ("Brazil", 0.04), ("Mexico", 0.035),
        ],
    },
    "product": {
        "sessions_7d": 4360,
        "wow": 0.214,
        "pages_per_session": 4.6,
        "engagement_rate": 0.742,
        "avg_session_duration": 312.0,
        "new_user_share": 0.21,
        "channels": [
            ("Direct", 0.58), ("Organic Search", 0.16), ("Referral", 0.13),
            ("Email", 0.08), ("Paid Search", 0.05),
        ],
        "devices": [("desktop", 0.82), ("mobile", 0.15), ("tablet", 0.03)],
        "top_pages": [
            ("/app/dashboard", 0.19), ("/signup", 0.12), ("/account/billing", 0.10),
            ("/app/reports", 0.09), ("/quote", 0.08), ("/app/settings", 0.07),
            ("/product/usage", 0.06), ("/account/team", 0.05),
            ("/app/integrations", 0.045), ("/signup/trial", 0.04),
        ],
        "landing_pages": [
            ("/app/dashboard", 0.24), ("/signup", 0.15), ("/quote", 0.10),
            ("/account/billing", 0.08), ("/app/reports", 0.07),
            ("/signup/trial", 0.06), ("/product/usage", 0.05), ("/account/team", 0.04),
        ],
        "countries": [
            ("United States", 0.68), ("Canada", 0.08), ("United Kingdom", 0.07),
            ("Australia", 0.05), ("Germany", 0.04), ("Mexico", 0.03),
        ],
    },
}

# B2B weekday shape: weekdays heavy, weekends light. Monday = 0.
_WEEKDAY_WEIGHT = {0: 1.18, 1: 1.22, 2: 1.20, 3: 1.14, 4: 0.98, 5: 0.56, 6: 0.52}


def _seed_float(*parts):
    """Deterministic float in [0, 1) from arbitrary string parts."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _distribute(total, weights):
    """Split an integer total across weights, preserving the exact sum."""
    s = sum(weights) or 1.0
    raw = [total * w / s for w in weights]
    ints = [int(round(x)) for x in raw]
    drift = total - sum(ints)
    if ints:
        idx = max(range(len(ints)), key=lambda i: raw[i])
        ints[idx] += drift
    return ints


def _now():
    return datetime.now(timezone.utc)


def build_demo_raw(site):
    """Return a raw GA4 payload (fetch.py schema) for one site's sample profile."""
    site_id = site["id"]
    profile = PROFILES.get(site_id)
    if profile is None:
        # Unknown site id: fall back to the marketing profile shape.
        profile = PROFILES["primary"]

    sessions = int(profile["sessions_7d"])
    wow = profile["wow"]
    pps = profile["pages_per_session"]

    prior_sessions = int(round(sessions / (1 + wow)))
    users = int(round(sessions * 0.82))
    prior_users = int(round(prior_sessions * 0.82))
    pageviews = int(round(sessions * pps))
    prior_pageviews = int(round(prior_sessions * pps))

    # Rolling 28d: current week plus ~3 prior weeks, mild upward drift.
    sessions_28d = int(round(sessions * 3.86))
    users_28d = int(round(users * 3.86))
    pageviews_28d = int(round(pageviews * 3.86))

    # Channel, device, country, landing splits.
    ch_labels = [c[0] for c in profile["channels"]]
    sources = [
        {"dimension": lbl, "value": v}
        for lbl, v in zip(ch_labels, _distribute(sessions, [c[1] for c in profile["channels"]]))
    ]
    dev_labels = [d[0] for d in profile["devices"]]
    devices = [
        {"dimension": lbl, "value": v}
        for lbl, v in zip(dev_labels, _distribute(sessions, [d[1] for d in profile["devices"]]))
    ]
    country_labels = [c[0] for c in profile["countries"]]
    countries = [
        {"dimension": lbl, "value": v}
        for lbl, v in zip(country_labels, _distribute(sessions, [c[1] for c in profile["countries"]]))
    ]
    page_labels = [p[0] for p in profile["top_pages"]]
    top_pages = [
        {"dimension": lbl, "value": v}
        for lbl, v in zip(page_labels, _distribute(pageviews, [p[1] for p in profile["top_pages"]]))
    ]
    landing_labels = [p[0] for p in profile["landing_pages"]]
    landing_pages = [
        {"dimension": lbl, "value": v}
        for lbl, v in zip(landing_labels, _distribute(sessions, [p[1] for p in profile["landing_pages"]]))
    ]

    # New vs returning.
    new_users = int(round(users * profile["new_user_share"]))
    returning_users = users - new_users
    new_sessions = int(round(sessions * (profile["new_user_share"] * 0.9)))
    returning_sessions = sessions - new_sessions
    new_vs_returning = [
        {"dimension": "new", "activeUsers": new_users, "sessions": new_sessions},
        {"dimension": "returning", "activeUsers": returning_users, "sessions": returning_sessions},
    ]

    # 14-day daily trend ending yesterday: most recent 7 days sum to `sessions`,
    # the earlier 7 to `prior_sessions`, distributed by B2B weekday shape with a
    # small deterministic jitter so the line reads naturally.
    today = _now().date()
    days = [today - timedelta(days=offset) for offset in range(14, 0, -1)]  # oldest -> yesterday
    early, recent = days[:7], days[7:]

    def _weighted(day_list, total):
        weights = []
        for d in day_list:
            base = _WEEKDAY_WEIGHT[d.weekday()]
            jitter = 0.85 + 0.30 * _seed_float(site_id, d.isoformat())
            weights.append(base * jitter)
        return _distribute(total, weights)

    early_sessions = _weighted(early, prior_sessions)
    recent_sessions = _weighted(recent, sessions)

    daily_trend = []
    for d, s in list(zip(early, early_sessions)) + list(zip(recent, recent_sessions)):
        daily_trend.append({
            "dimension": d.strftime("%Y%m%d"),
            "sessions": s,
            "activeUsers": int(round(s * 0.82)),
            "screenPageViews": int(round(s * pps)),
        })

    return {
        "status": "ok",
        "demo": True,
        "site_id": site_id,
        "generated_at": _now().isoformat(),
        "core": {
            "current_7d": {"sessions": sessions, "activeUsers": users, "screenPageViews": pageviews},
            "prior_7d": {"sessions": prior_sessions, "activeUsers": prior_users, "screenPageViews": prior_pageviews},
            "rolling_28d": {"sessions": sessions_28d, "activeUsers": users_28d, "screenPageViews": pageviews_28d},
        },
        "top_pages": top_pages,
        "sources": sources,
        "devices": devices,
        "daily_trend": daily_trend,
        "landing_pages": landing_pages,
        "countries": countries,
        "new_vs_returning": new_vs_returning,
        "engagement_7d": {
            "engagementRate": profile["engagement_rate"],
            "averageSessionDuration": profile["avg_session_duration"],
            "engagedSessions": int(round(sessions * profile["engagement_rate"])),
        },
    }
