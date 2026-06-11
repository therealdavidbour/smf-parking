# SMF Parking

Collect Sacramento International Airport parking data into JSON files stored in
this GitHub repository.

The live occupancy source is:

```text
https://smf-count.ipparkingna.com/live-count
```

## Data Files

The scraper writes two repo-backed data files:

- `data/latest.json`: the newest scrape snapshot
- `data/occupancy/YYYY-MM-DD.jsonl`: one compact JSON line per scrape

Each JSONL line has this shape:

```json
{"lots":[{"free_spaces":273,"id":8,"name":"Daily Lot","occupied_spaces":2730,"total_capacity":3003}],"scraped_at":"2026-06-10T12:00:00+00:00"}
```

## Usage

Run one scrape locally:

```bash
SMF_COUNT_INSECURE_TLS=true uv run python query.py
```

Configuration is set with environment variables:

- `SMF_COUNT_URL`: live-count endpoint, defaults to the SMF live source
- `SMF_COUNT_INSECURE_TLS`: set to `true` to skip TLS certificate verification
- `REQUEST_TIMEOUT_SECONDS`: request timeout, defaults to `10`

## GitHub Actions

`.github/workflows/scrape.yml` runs every 5 minutes, updates the JSON data files,
and commits them back to the repository with `GITHUB_TOKEN`.
