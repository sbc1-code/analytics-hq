"""
fetch.py -- Pull GA4 data for each configured site.
Writes data/{site_id}_raw.json per site.
Degrades gracefully when GA4 credentials or numeric property IDs are missing.
Property IDs can come from config/sites.json or GA4_PROPERTY_ID_<SITE_ID> env vars.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("data")
CONFIG_PATH = Path("config/sites.json")


def load_config():
    return json.loads(CONFIG_PATH.read_text())


def load_sites():
    return load_config()["sites"]


def demo_enabled():
    """Demo mode renders a sample dashboard when no live GA4 config exists.

    Explicit override via ANALYTICS_HQ_DEMO (1/0); otherwise the config flag
    demo_when_unconfigured decides.
    """
    flag = os.environ.get("ANALYTICS_HQ_DEMO", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return bool(load_config().get("demo_when_unconfigured", False))


def has_live_config(sites):
    """True only when real credentials AND at least one numeric property exist."""
    creds = (
        os.environ.get("GA4_SERVICE_ACCOUNT_JSON", "").strip()
        or os.environ.get("GA4_SERVICE_ACCOUNT_FILE", "").strip()
    )
    any_property = any(resolve_property_id(site) for site in sites)
    return bool(creds and any_property)


def write_demo(sites):
    """Write deterministic sample raw data for every site (demo mode)."""
    from demo_data import build_demo_raw

    DATA_DIR.mkdir(exist_ok=True)
    for site in sites:
        raw = build_demo_raw(site)
        (DATA_DIR / f"{site['id']}_raw.json").write_text(json.dumps(raw, indent=2))
        print(f"  [{site['id']}] demo sample written -- sessions 7d: {raw['core']['current_7d']['sessions']}")


def write_unavailable(site_id, reason):
    DATA_DIR.mkdir(exist_ok=True)
    out = {
        "status": "unavailable",
        "reason": reason,
        "site_id": site_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (DATA_DIR / f"{site_id}_raw.json").write_text(json.dumps(out, indent=2))
    print(f"  [{site_id}] unavailable -- {reason}")


def is_valid_property_id(value):
    """Return True only for GA4 numeric property IDs."""
    candidate = str(value or "").strip()
    upper = candidate.upper()
    if not candidate or upper == "TBD":
        return False
    if upper.startswith("GA4_PROPERTY_ID_"):
        return False
    if upper.startswith("G-"):
        return False
    if "XXXX" in upper or "YYYY" in upper or "ZZZZ" in upper:
        return False
    return candidate.isdigit()


def resolve_property_id(site, environ=None):
    """Resolve GA4 numeric property ID from env overrides or static config."""
    environ = os.environ if environ is None else environ
    site_id = str(site.get("id", "")).strip()
    configured = str(site.get("numeric_property_id", "")).strip()
    configured_env = str(site.get("property_id_env", "")).strip()

    candidates = []
    if configured_env:
        candidates.append(environ.get(configured_env, "").strip())
    if site_id:
        candidates.append(environ.get(f"GA4_PROPERTY_ID_{site_id.upper()}", "").strip())
    candidates.append(configured)

    for candidate in candidates:
        if is_valid_property_id(candidate):
            return candidate
    return None


def run_report(client, property_ref, date_ranges, dimensions, metrics, limit=10, order_metric=None, dimension_filter=None):
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Filter,
        FilterExpression,
        Metric,
        OrderBy,
        RunReportRequest,
    )

    req = RunReportRequest(
        property=property_ref,
        date_ranges=date_ranges,
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        limit=limit,
    )
    if order_metric:
        req.order_bys = [OrderBy(metric=OrderBy.MetricOrderBy(metric_name=order_metric), desc=True)]
    if dimension_filter is not None:
        req.dimension_filter = dimension_filter
    return client.run_report(req)


def run_report_optional(client, property_ref, date_ranges, dimensions, metrics, limit=10, order_metric=None, label="report"):
    try:
        return run_report(
            client,
            property_ref,
            date_ranges=date_ranges,
            dimensions=dimensions,
            metrics=metrics,
            limit=limit,
            order_metric=order_metric,
        )
    except Exception as e:
        print(f"  [WARN] optional {label} unavailable: {str(e)[:120]}")
        return None


def parse_dim(response):
    if response is None:
        return []
    rows = []
    for row in response.rows:
        rows.append({
            "dimension": row.dimension_values[0].value,
            "value": int(row.metric_values[0].value) if row.metric_values[0].value else 0,
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
        "engagedSessions": 0,
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


def prepare_credentials(sites):
    sa_json = os.environ.get("GA4_SERVICE_ACCOUNT_JSON", "").strip()
    sa_file = os.environ.get("GA4_SERVICE_ACCOUNT_FILE", "").strip()

    if sa_file:
        sa_path = Path(sa_file)
        if sa_path.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_path)
            return str(sa_path), False
        print(f"GA4_SERVICE_ACCOUNT_FILE path not found: {sa_file}")
        for site in sites:
            write_unavailable(site["id"], "credentials_file_not_found")
        return None, False

    if not sa_json:
        print("GA4 credentials not set (GA4_SERVICE_ACCOUNT_JSON or GA4_SERVICE_ACCOUNT_FILE) -- sites will show setup status.")
        for site in sites:
            reason = "property_id_not_configured" if not resolve_property_id(site) else "ga4_credentials_not_configured"
            write_unavailable(site["id"], reason)
        return None, False

    try:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(sa_json)
        tmp.close()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name
        return tmp.name, True
    except Exception as e:
        print(f"Failed to write credentials: {e}")
        for site in sites:
            write_unavailable(site["id"], "credentials_write_error")
        return None, False


def fetch_site(client, site):
    from google.analytics.data_v1beta.types import DateRange

    site_id = site["id"]
    prop_id = resolve_property_id(site)

    if not prop_id:
        write_unavailable(site_id, "property_id_not_configured")
        return

    prop_ref = f"properties/{prop_id}"
    print(f"  [{site_id}] Fetching from {prop_ref}...")

    try:
        core = run_report(
            client,
            prop_ref,
            date_ranges=[
                DateRange(start_date="7daysAgo", end_date="yesterday"),
                DateRange(start_date="14daysAgo", end_date="8daysAgo"),
                DateRange(start_date="28daysAgo", end_date="yesterday"),
            ],
            dimensions=[],
            metrics=["sessions", "activeUsers", "screenPageViews"],
            limit=1,
        )

        top_pages = run_report(
            client,
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["pagePath"],
            metrics=["screenPageViews"],
            limit=10,
            order_metric="screenPageViews",
        )

        sources = run_report(
            client,
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["sessionDefaultChannelGroup"],
            metrics=["sessions"],
            limit=8,
            order_metric="sessions",
        )

        devices = run_report(
            client,
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["deviceCategory"],
            metrics=["sessions"],
            limit=5,
            order_metric="sessions",
        )

        daily_trend = run_report_optional(
            client,
            prop_ref,
            date_ranges=[DateRange(start_date="14daysAgo", end_date="yesterday")],
            dimensions=["date"],
            metrics=["sessions", "activeUsers", "screenPageViews"],
            limit=30,
            label="daily_trend",
        )

        landing_pages = run_report_optional(
            client,
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["landingPagePlusQueryString"],
            metrics=["sessions"],
            limit=12,
            order_metric="sessions",
            label="landing_pages",
        )

        countries = run_report_optional(
            client,
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["country"],
            metrics=["sessions"],
            limit=10,
            order_metric="sessions",
            label="countries",
        )

        new_vs_returning = run_report_optional(
            client,
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=["newVsReturning"],
            metrics=["activeUsers", "sessions"],
            limit=5,
            label="new_vs_returning",
        )

        engagement = run_report_optional(
            client,
            prop_ref,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=[],
            metrics=["engagementRate", "averageSessionDuration", "engagedSessions"],
            limit=1,
            label="engagement",
        )

        raw = {
            "status": "ok",
            "site_id": site_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "core": {
                "current_7d": {m: 0 for m in ["sessions", "activeUsers", "screenPageViews"]},
                "prior_7d": {m: 0 for m in ["sessions", "activeUsers", "screenPageViews"]},
                "rolling_28d": {m: 0 for m in ["sessions", "activeUsers", "screenPageViews"]},
            },
            "top_pages": parse_dim(top_pages),
            "sources": parse_dim(sources),
            "devices": parse_dim(devices),
            "daily_trend": parse_dim_multi(daily_trend),
            "landing_pages": parse_dim(landing_pages),
            "countries": parse_dim(countries),
            "new_vs_returning": parse_dim_multi(new_vs_returning),
            "engagement_7d": parse_engagement(engagement),
        }

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


def main():
    DATA_DIR.mkdir(exist_ok=True)
    sites = load_sites()

    if not has_live_config(sites) and demo_enabled():
        print("No live GA4 config detected -- writing sample (demo) data.")
        write_demo(sites)
        print("fetch.py done (demo mode).")
        return 0

    creds_path, should_cleanup = prepare_credentials(sites)

    if not creds_path:
        print("fetch.py done.")
        return 0

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        client = BetaAnalyticsDataClient()
    except Exception as e:
        print(f"GA4 library init failed: {e}")
        for site in sites:
            write_unavailable(site["id"], "ga4_library_error")
        return 0

    for site in sites:
        fetch_site(client, site)

    if should_cleanup and creds_path and os.path.exists(creds_path):
        os.unlink(creds_path)

    print("fetch.py done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
