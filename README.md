# Analytics HQ

Connector-first GA4 reporting dashboard for multiple web properties, published with GitHub Pages.

When no live GA4 credentials are configured, the pipeline renders a fully populated **sample dashboard** on synthetic data for a fictional company ("Acme Cloud"), clearly badged as sample data, so the report can be evaluated end to end. The moment a GA4 service account and numeric property IDs are wired in, it switches to live figures automatically and the sample is bypassed.

Demo mode is controlled by `demo_when_unconfigured` in `config/sites.json` (default `true`) and can be forced on or off with the `ANALYTICS_HQ_DEMO` environment variable. Sample numbers are deterministic per calendar day, so scheduled runs do not churn; only the trailing 14-day date labels roll forward.

## Pipeline

Stages:

1. `qa` - compile-check Python scripts
2. `fetch` - pull GA4 data per site into `data/*_raw.json`
3. `analyze` - compute WoW deltas and summary datasets
4. `report` - build alert JSON + render `public/` HTML
5. `report` - render `public/` and the repository-root GitHub Pages HTML
6. `commit` - publish updated static output when the workflow has changes

## Business Lens

The dashboard intentionally translates traffic into customer-need signals:

- `revenue_role` per property (business purpose of the site)
- `intent_path_keywords` per property (high-value path patterns)
- intent views and intent-share signals from top pages
- primary channel and momentum callouts for stakeholder readouts

You can tune these in `config/sites.json` without code changes.

## Brand Styling

Dashboard uses a clean, neutral design system:

- Primary font stack: `Montserrat`, fallback `Arial`
- Core palette:
  - Accent green `#2f6f5f`
  - Rich black `#000000`
  - Gray `#A2ACB4`
  - Dark gray `#2D3031`
  - Accent orange `#F68B1F`
- Per-site accent colors are configurable in `config/sites.json`.

## Required CI/CD Variables

Set these in GitHub Actions secrets:

- `GA4_SERVICE_ACCOUNT_JSON` - full service-account JSON as a text secret

Alternative:

- `GA4_SERVICE_ACCOUNT_FILE` - local/service runner path to a service-account JSON file

Optional override vars (if you do not want IDs in repo config):

- `GA4_PROPERTY_ID_PRIMARY`
- `GA4_PROPERTY_ID_SUPPORT`
- `GA4_PROPERTY_ID_PRODUCT`

`fetch.py` uses env vars first, then `config/sites.json` `numeric_property_id`.
Placeholder strings such as `GA4_PROPERTY_ID_1`, `G-XXXXXXXXXX`, and non-numeric values are treated as unconfigured.

## GA4 Access Checklist

1. Create/select a Google Cloud service account with GA Data API enabled.
2. Add the service-account email as `Viewer` (or higher) on each GA4 property.
3. Copy each GA4 numeric property ID from GA4 Admin and either:
   - set the optional override vars above, or
   - keep IDs in `config/sites.json`.
4. Run the GitHub Actions workflow manually once and confirm all sites show `status: ok`.

## Local Run

```bash
pip install -r requirements.txt
python scripts/fetch.py
python scripts/analyze.py
python scripts/alert.py
python scripts/report.py
```
