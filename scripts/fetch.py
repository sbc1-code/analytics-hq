"""
fetch.py -- Pull GA4 data for each configured site.
Writes data/{site_id}_raw.json per site.
Degrades gracefully when GA4_SERVICE_ACCOUNT_JSON is not set or property ID is missing.
Property IDs can come from config/sites.json or GA4_PROPERTY_ID_<N> env vars.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

CONFIG_PATH = Path("config/sites.json")
sites = json.loads(CONFIG_PATH.read_text())["sites"]

SA_JSON = os.environ.get("GA4_SERVICE_ACCOUNT_JSON", "").strip()
SA_FILE = os.environ.get("GA4_SERVICE_ACCOUNT_FILE", "").strip()
creds_path = None

def write_unavailable(site_id, reason):
    out = {"status": "unavailable", "reason": reason, "site_id": site_id, "generated_at": datetime.now(timezone.utc).isoformat()}
    (DATA_DIR / f"{site_id}_raw.json").write_text(json.dumps(out, indent=2))
    print(f"  [{site_id}] unavailable -- {reason}")


def resolve_property_id(site):
    """Resolve GA4 property ID from env overrides or static config."""
    site_id = str(site.get("id", "")).strip()
    configured = str(site.get("numeric_property_id", "")).strip()
    configured_env = str(site.get("property_id_env", "")).strip()

    candidates = []
    if configured_env:
        candidates.append(os.environ.get(configured_env, "").strip())
    if site_id:
        candidates.append(os.environ.get(f"GA4_PROPERTY_ID_{site_id.upper()}", "").strip())
    candidates.append(configured)

    for candidate in candidates:
        if candidate and candidate != "TBD":
            return candidate
    return None

# Check credentials
if SA_FILE:
    sa_path = Path(SA_FILE)
    if sa_path.exists():
        creds_path = str(sa_path)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
    else:
        print(f"GA4_SERVICE_ACCOUNT_FILE path not found: {SA_FILE}")
        for site in sites:
            write_unavailable(site["id"], "credentials_file_not_found")
        sys.exit(0)

if not SA_JSON and not creds_path:
    print("GA4 credentials not set (GA4_SERVICE_ACCOUNT_JSON or GA4_SERVICE_ACCOUNT_FILE) -- all sites will show as pending.")
    for site in sites:
        write_unavailable(site["id"], "ga4_credentials_not_configured")
    sys.exit(0)

# Write service account JSON to temp file
if not creds_path:
    try:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(SA_JSON)
        tmp.close()
        creds_path = tmp.name
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
    except Exception as e:
        print(f"Failed to write credentials: {e}")
        for site in sites:
            write_unavailable(site["id"], "credentials_write_error")
        sys.exit(0)

# Import GA4 library (only after pip install)
try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Metric, Dimension, OrderBy,
        FilterExpression, Filter
    )
    client = BetaAnalyticsDataClient()
except Exception as e:
    print(f"GA4 library init failed: {e}")
    for site in sites:
        write_unavailable(site["id"], "ga4_library_error")
    sys.exit(0)

def run_report(property_ref, date_ranges, dimensions, metrics, limit=10, order_metric=None, dimension_filter=None):
    req = RunReportRequest(
        property=property_ref,
        date_ranges=date_ranges,
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        limit=limit
    )
    if order_metric:
        req.order_bys = [OrderBy(metric=OrderBy.MetricOrderBy(metric_name=order_metric), desc=True)]
    if dimension_filter is not None:
        req.dimension_filter = dimension_filter
    return client.run_report(req)

def run_report_optional(property_ref, date_ranges, dimensions, metrics, limit=10, order_metric=None, label="report"):
    try:
        return run_report(
            property_ref,
            date_ranges=date_ranges,
            dimensions=dimensions,
            metrics=metrics,
            limit=limit,
            order_metric=order_metric
        )
    except Exception as e:
        print(f"  [WARN] optional {label} unavailable: {str(e)[:120]}")
        return None

for site in sites:
    site_id = site["id"]
    prop_id = resolve_property_id(site)

    if not prop_id:
        write_unavailable(site_id, "property_id_not_configured")
        continue

    prop_ref = f"properties/{prop_id}"
    print(f"  [{site_id}] Fetching from {prop_ref}...")

    try:
        # Core metrics: current 7d, prior 7d (for WoW), 28d
        core = run_report(
            prop_ref,
            date_ranges=[
                DateRange(start_date="7daysAgo",  end_date="yesterday"),
                DateRange(start_date="14daysAgo", end_date="8daysAgo"),
                DateRange(start_date="28daysAgo", end_date="yesterday"),
            ],
            dimensions=[],
            metrics=["sessions", "activeUsers", "screenPageViews"],
            limit=1
        )

        # Top pages (7d)
        top_pages = run_report(
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["pagePath"],
            metrics=["screenPageViews"],
            limit=10,
            order_metric="screenPageViews"
        )

        # Traffic sources (7d)
        sources = run_report(
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["sessionDefaultChannelGroup"],
            metrics=["sessions"],
            limit=8,
            order_metric="sessions"
        )

        # Device split (7d)
        devices = run_report(
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["deviceCategory"],
            metrics=["sessions"],
            limit=5,
            order_metric="sessions"
        )

        # Daily trend (14d)
        daily_trend = run_report_optional(
            prop_ref,
            date_ranges=[DateRange(start_date="14daysAgo", end_date="yesterday")],
            dimensions=["date"],
            metrics=["sessions", "activeUsers", "screenPageViews"],
            limit=30,
            label="daily_trend"
        )

        # Top landing pages (7d)
        landing_pages = run_report_optional(
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["landingPagePlusQueryString"],
            metrics=["sessions"],
            limit=12,
            order_metric="sessions",
            label="landing_pages"
        )

        # Top countries (7d)
        countries = run_report_optional(
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["country"],
            metrics=["sessions"],
            limit=10,
            order_metric="sessions",
            label="countries"
        )

        # New vs returning (7d)
        new_vs_returning = run_report_optional(
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["newVsReturning"],
            metrics=["activeUsers", "sessions"],
            limit=5,
            label="new_vs_returning"
        )

        # Engagement quality (7d)
        engagement = run_report_optional(
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=[],
            metrics=["engagementRate", "averageSessionDuration", "engagedSessions"],
            limit=1,
            label="engagement"
        )

        def parse_core(response):
            result = {}
            for row in response.rows:
                dr_idx = row.dimension_values[0].value if response.dimension_headers else "0"
                for i, mv in enumerate(row.metric_values):
                    key = response.metric_headers[i].name
                    result.setdefault(str(dr_idx), {})[key] = int(mv.value) if mv.value else 0
            return result

        def parse_dim(response):
            if response is None:
                return []
            rows = []
            for row in response.rows:
                rows.append({
                    "dimension": row.dimension_values[0].value,
                    "value": int(row.metric_values[0].value) if row.metric_values[0].value else 0
                })
            return rows

        def parse_dim_multi(response):
            if response is None:
                return []
            rows = []
            for row in response.rows:
                item = {"dimension": row.dimension_values[0].value}
                for i, mv in enumerate(row.metric_values):
                    metric_name = response.metric_headers[i].name
                    value = mv.value
                    if value is None or value == "":
                        item[metric_name] = 0
                    else:
                        try:
                            item[metric_name] = int(float(value))
                        except Exception:
                            item[metric_name] = 0
                rows.append(item)
            return rows

        def parse_engagement(response):
            base = {
                "engagementRate": 0.0,
                "averageSessionDuration": 0.0,
                "engagedSessions": 0
            }
            if response is None or not response.rows:
                return base

            row = response.rows[0]
            for i, mv in enumerate(row.metric_values):
                name = response.metric_headers[i].name
                raw_value = mv.value or "0"
                if name == "engagedSessions":
                    try:
                        base[name] = int(float(raw_value))
                    except Exception:
                        base[name] = 0
                else:
                    try:
                        base[name] = float(raw_value)
                    except Exception:
                        base[name] = 0.0
            return base

        raw = {
            "status": "ok",
            "site_id": site_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "core": {
                "current_7d":  {m: 0 for m in ["sessions","activeUsers","screenPageViews"]},
                "prior_7d":    {m: 0 for m in ["sessions","activeUsers","screenPageViews"]},
                "rolling_28d": {m: 0 for m in ["sessions","activeUsers","screenPageViews"]},
            },
            "top_pages": parse_dim(top_pages),
            "sources":   parse_dim(sources),
            "devices":   parse_dim(devices),
            "daily_trend": parse_dim_multi(daily_trend),
            "landing_pages": parse_dim(landing_pages),
            "countries": parse_dim(countries),
            "new_vs_returning": parse_dim_multi(new_vs_returning),
            "engagement_7d": parse_engagement(engagement),
        }

        def parse_date_range_index(label):
            if not label:
                return 0
            if label.isdigit():
                return int(label)
            if label.startswith("date_range_"):
                tail = label.rsplit("_", 1)[-1]
                if tail.isdigit():
                    return int(tail)
            return 0

        for row in core.rows:
            dr_label = row.dimension_values[0].value if core.dimension_headers else "0"
            dr_idx = parse_date_range_index(dr_label)
            keys = ["current_7d", "prior_7d", "rolling_28d"]
            target = keys[dr_idx] if dr_idx < len(keys) else "current_7d"
            for i, mv in enumerate(row.metric_values):
                metric = core.metric_headers[i].name
                raw["core"][target][metric] = int(mv.value) if mv.value else 0

        (DATA_DIR / f"{site_id}_raw.json").write_text(json.dumps(raw, indent=2))
        print(f"  [{site_id}] OK -- sessions 7d: {raw['core']['current_7d']['sessions']}")

    except Exception as e:
        write_unavailable(site_id, f"api_error: {str(e)[:120]}")

# Cleanup temp creds
if creds_path and SA_FILE == "" and os.path.exists(creds_path):
    os.unlink(creds_path)

print("fetch.py done.")
