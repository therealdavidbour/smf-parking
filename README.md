# SMF Parking

Collect Sacramento International Airport parking data into JSON files stored in
this GitHub repository.

The scraper reads the FlySMF parking page and lazy-loads its parking
availability table:

```text
https://flysmf.gov/to-and-from/parking
```

## Data Files

The scraper writes these repo-backed files:

- `data/latest.json`: the newest scrape snapshot
- `data/occupancy/YYYY-MM-DD.jsonl`: one compact JSON line per scrape
- `data/lot_config.json`: lot display-name aliases and hard capacity values
- `index.html`: a static parking occupancy history chart generated from all
  stored JSONL snapshots, oldest first

The static page markup lives in `templates/occupancy_report.html`; `query.py`
injects the generated chart JSON into that template. The charts are rendered in
the browser with Apache ECharts loaded from jsDelivr.

Configured capacity values are used to estimate occupied spaces from records
that only report free spaces. Closed lots without a free-space value remain
unknown for occupied-space estimates.

Each JSONL line has this shape:

```json
{"lots":[{"free_spaces":273,"id":2,"name":"Daily A","pricing":"$2 /30min | $14 /day max","status":"open"}],"scraped_at":"2026-06-10T12:00:00+00:00"}
```

## Usage

Run one scrape locally:

```bash
uv run python query.py
```

Configuration is set with environment variables:

- `SMF_PARKING_URL`: parking page URL, defaults to the SMF parking page
- `SMF_PARKING_INSECURE_TLS`: set to `true` to skip TLS certificate verification
- `REQUEST_TIMEOUT_SECONDS`: request timeout, defaults to `10`

## GitHub Actions

`.github/workflows/scrape.yml` runs every 5 minutes, updates the JSON data files,
and commits them back to the repository with `GITHUB_TOKEN`.
