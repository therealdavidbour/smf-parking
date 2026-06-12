# SMF Parking GitHub JSON Implementation

## Overview

This project uses GitHub as the storage layer for scraped Sacramento
International Airport parking data. A scheduled GitHub Actions workflow runs the
scraper every 5 minutes, writes shared JSON data into the repository, and commits
the changed files back to the default branch.

## Data Storage

The scraper writes:

- `data/latest.json`
  - Rewritten every scrape.
  - Contains the newest snapshot.
- `data/occupancy/YYYY-MM-DD.jsonl`
  - Appended every scrape.
  - Uses UTC dates from the scrape timestamp.
  - Keeps one compact JSON object per line.
- `index.html`
  - Rebuilt every scrape from all stored occupancy JSONL files.
  - Embeds chart-ready history ordered from the oldest scrape to the newest.
  - Shows total available spaces, per-lot trends, and observed fluctuation.
  - Rendered from `templates/occupancy_report.html`.
  - Uses Apache ECharts from jsDelivr for browser-side chart interaction.

Snapshot shape:

```json
{"lots":[{"free_spaces":273,"id":2,"name":"Daily A","pricing":"$2 /30min | $14 /day max","status":"open"}],"scraped_at":"2026-06-10T12:00:00+00:00"}
```

With a 5-minute interval and the current 5-lot payload, expected raw JSONL size
is approximately:

- 152 KiB per day
- 4.4 MiB per month
- 54 MiB per year

History is kept indefinitely by default.

## Runtime Configuration

Configuration is environment-variable based:

```text
SMF_PARKING_URL=https://flysmf.gov/to-and-from/parking
SMF_PARKING_INSECURE_TLS=false
REQUEST_TIMEOUT_SECONDS=10
```

`SMF_PARKING_URL` and `REQUEST_TIMEOUT_SECONDS` have defaults. TLS verification is
enabled by default unless `SMF_PARKING_INSECURE_TLS` is set to a truthy value such
as `true`, `1`, `yes`, or `on`.

The FlySMF page renders parking availability through a lazy Livewire component.
The scraper first requests the parking page, extracts the `lots` component's
`wire:snapshot`, `x-intersect` lazy-load payload, CSRF token, and
`data-update-uri`, then posts the lazy-load call to `/livewire/update`. The
returned table provides `Lot`, `Open Spaces`, and `Pricing`; occupied-space and
capacity values are not available from this source.

## Workflows

### Scrape Parking Data

`.github/workflows/scrape.yml`:

- Runs every 5 minutes and on manual dispatch.
- Installs dependencies with `uv sync --locked`.
- Runs `uv run python query.py`.
- Commits `data/latest.json` and `data/occupancy` only when they changed.
- Uses workflow concurrency to avoid concurrent repo writers.

## Local Development

Run a single scrape:

```bash
uv run python query.py
```

This creates or updates:

```text
data/latest.json
data/occupancy/YYYY-MM-DD.jsonl
index.html
```

## Testing

Recommended checks:

- Compile the script with `uv run python -m py_compile query.py`.
- Run one local scrape with `uv run python query.py`.
- Validate `data/latest.json` with `uv run python -m json.tool data/latest.json`.
- Validate each line in the daily JSONL file as independent JSON.
- Confirm GitHub Actions commits data changes.
