# Analytics HQ

Multi-site GA4 dashboard for multiple web properties, published via GitLab Pages.

## Pipeline

Stages:

1. `qa` - compile-check Python scripts
2. `fetch` - pull GA4 data per site into `data/*_raw.json`
3. `analyze` - compute WoW deltas and summary datasets
4. `report` - build alert JSON + render `public/` HTML
5. `pages` - deploy `public/` to GitLab Pages

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
  - Accent green `#30DC30`
  - Rich black `#000000`
  - Gray `#A2ACB4`
  - Dark gray `#2D3031`
  - Accent orange `#F68B1F`
- Per-site accent colors are configurable in `config/sites.json`.

## Required CI/CD Variables

Set these in GitLab project CI/CD settings:

- `GA4_SERVICE_ACCOUNT_FILE` - service-account JSON as a **File** variable (preferred)

Alternative:

- `GA4_SERVICE_ACCOUNT_JSON` - full service-account JSON as text variable

Optional override vars (if you do not want IDs in repo config):

- `GA4_PROPERTY_ID_1`
- `GA4_PROPERTY_ID_2`
- `GA4_PROPERTY_ID_3`

`fetch.py` uses env vars first, then `config/sites.json` `numeric_property_id`.

## GA4 Access Checklist

1. Create/select a Google Cloud service account with GA Data API enabled.
2. Add the service-account email as `Viewer` (or higher) on each GA4 property.
3. Copy each GA4 numeric property ID from GA4 Admin and either:
   - set the optional override vars above, or
   - keep IDs in `config/sites.json`.
4. Run the pipeline manually once (`Run pipeline`) and confirm all sites show `status: ok`.

## Local Run

```bash
pip install -r requirements.txt
python scripts/fetch.py
python scripts/analyze.py
python scripts/alert.py
python scripts/report.py
```
