"""
alert.py -- Evaluate QC alert conditions and write data/alerts.json.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("data")
CONFIG_PATH  = Path("config/sites.json")
ALERTS_CONFIG = Path("config/alerts.json")

sites = json.loads(CONFIG_PATH.read_text())["sites"]
thresholds = json.loads(ALERTS_CONFIG.read_text())["alerts"]

alerts = []

for site in sites:
    site_id = site["id"]
    analyzed_path = DATA_DIR / f"{site_id}_analyzed.json"

    if not analyzed_path.exists():
        alerts.append({
            "site_id": site_id,
            "site_name": site["name"],
            "type": "data_unavailable",
            "severity": "warning",
            "message": "Analysis file not found -- fetch may have failed."
        })
        continue

    data = json.loads(analyzed_path.read_text())

    if data.get("status") != "ok":
        reason = data.get("reason", "unknown")
        if reason == "ga4_credentials_not_configured":
            message = "GA4 credentials not configured. Set GA4_SERVICE_ACCOUNT_FILE (preferred) or GA4_SERVICE_ACCOUNT_JSON in CI/CD variables."
        elif reason == "property_id_not_configured":
            message = f"GA4 property ID is missing. Set GA4_PROPERTY_ID_{site_id.upper()} in CI/CD variables or numeric_property_id in config/sites.json."
        elif reason.startswith("api_error"):
            message = f"GA4 API error: {reason}"
        elif reason == "ga4_library_error":
            message = "GA4 library initialization failed. Check dependency install in pipeline."
        elif reason == "credentials_write_error":
            message = "Could not write GA4 credentials temp file in runner environment."
        elif reason == "credentials_file_not_found":
            message = "GA4_SERVICE_ACCOUNT_FILE path was not found in runner environment. Check CI/CD variable type and scope."
        else:
            message = f"Data unavailable: {reason}"
        alerts.append({
            "site_id": site_id,
            "site_name": site["name"],
            "type": "data_unavailable",
            "severity": "warning",
            "message": message
        })
        continue

    kpis = data.get("kpis", {})
    sessions_7d  = kpis.get("sessions_7d", {}).get("raw", 0)
    sessions_wow = kpis.get("sessions_7d", {}).get("wow", {})

    # Zero data flag
    if thresholds.get("zero_data_flag") and sessions_7d == 0:
        alerts.append({
            "site_id": site_id,
            "site_name": site["name"],
            "type": "zero_data",
            "severity": "critical",
            "message": "Zero sessions recorded in the last 7 days. Tracking may be broken."
        })
        continue

    # WoW drop
    wow_val = sessions_wow.get("value")
    threshold = thresholds.get("wow_drop_threshold_pct", 25)
    if wow_val is not None and wow_val <= -threshold:
        prior = kpis.get("sessions_7d", {}).get("wow", {})
        alerts.append({
            "site_id": site_id,
            "site_name": site["name"],
            "type": "wow_drop",
            "severity": "critical",
            "message": f"Sessions dropped {abs(wow_val):.1f}% week-over-week (threshold: {threshold}%)."
        })

has_critical = any(a["severity"] == "critical" for a in alerts)

output = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "has_alerts": len(alerts) > 0,
    "has_critical": has_critical,
    "alerts": alerts
}

(DATA_DIR / "alerts.json").write_text(json.dumps(output, indent=2))

print(f"alert.py done -- {len(alerts)} alert(s), critical: {has_critical}")
for a in alerts:
    print(f"  [{a['site_id']}] {a['type']}: {a['message']}")
