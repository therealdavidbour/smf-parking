from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import html
import json
import os
from pathlib import Path
import re
from typing import Any

import requests


DEFAULT_PARKING_URL = "https://flysmf.gov/to-and-from/parking"
DATA_DIR = Path("data")
LATEST_PATH = DATA_DIR / "latest.json"
OCCUPANCY_DIR = DATA_DIR / "occupancy"
LOT_CONFIG_PATH = DATA_DIR / "lot_config.json"
STATIC_REPORT_PATH = Path("index.html")
REPORT_TEMPLATE_PATH = Path("templates") / "occupancy_report.html"


@dataclass(frozen=True)
class ParkingLot:
    scraped_at: datetime
    id: int
    name: str
    free_spaces: int | None
    status: str
    pricing: str

    @classmethod
    def from_row(cls, row_number: int, row: list[str], scraped_at: datetime) -> "ParkingLot":
        if len(row) < 2:
            raise ValueError(f"Expected at least lot and open-space cells, got {row!r}")

        raw_spaces = row[1].replace(",", "")
        free_spaces = int(raw_spaces) if raw_spaces.isdigit() else None
        status = "open" if free_spaces is not None else row[1].strip().lower()

        return cls(
            scraped_at=scraped_at,
            id=row_number,
            name=row[0],
            free_spaces=free_spaces,
            status=status,
            pricing=row[2] if len(row) > 2 else "",
        )

    def to_json_dict(self) -> dict[str, Any]:
        lot = asdict(self)
        lot.pop("scraped_at")
        return lot


class ParkingPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.csrf_token: str | None = None
        self.update_uri: str | None = None
        self.component_snapshot: str | None = None
        self.lazy_payload: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}

        if tag == "script" and attr_map.get("data-update-uri"):
            self.csrf_token = attr_map.get("data-csrf")
            self.update_uri = attr_map.get("data-update-uri")
            return

        if tag != "div" or "wire:snapshot" not in attr_map:
            return

        snapshot = attr_map["wire:snapshot"]
        if '"name":"lots"' not in snapshot and '"name": "lots"' not in snapshot:
            return

        intersect = attr_map.get("x-intersect", "")
        match = re.search(r"__lazyLoad\('([^']+)'\)", intersect)
        if not match:
            return

        self.component_snapshot = snapshot
        self.lazy_payload = html.unescape(match.group(1))


class AvailabilityTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag == "td" and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            text = data.strip()
            if text:
                self._current_cell.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._current_row is not None and self._current_cell is not None:
            self._current_row.append(" ".join(self._current_cell))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = None


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_parking_page(page_html: str) -> ParkingPageParser:
    parser = ParkingPageParser()
    parser.feed(page_html)

    missing = [
        name
        for name, value in {
            "data-csrf": parser.csrf_token,
            "data-update-uri": parser.update_uri,
            "wire:snapshot": parser.component_snapshot,
            "x-intersect lazy payload": parser.lazy_payload,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Parking page is missing expected Livewire fields: {', '.join(missing)}")

    return parser


def load_availability_html(
    session: requests.Session,
    parking_url: str,
    page: ParkingPageParser,
    timeout: float,
    verify_tls: bool,
) -> str:
    assert page.csrf_token is not None
    assert page.update_uri is not None
    assert page.component_snapshot is not None
    assert page.lazy_payload is not None

    response = session.post(
        requests.compat.urljoin(parking_url, page.update_uri),
        json={
            "_token": page.csrf_token,
            "components": [
                {
                    "snapshot": page.component_snapshot,
                    "updates": {},
                    "calls": [
                        {
                            "path": "",
                            "method": "__lazyLoad",
                            "params": [page.lazy_payload],
                        }
                    ],
                }
            ],
        },
        headers={
            "Accept": "application/json",
            "Referer": parking_url,
            "X-Livewire": "true",
        },
        timeout=timeout,
        verify=verify_tls,
    )
    response.raise_for_status()

    payload = response.json()
    try:
        availability_html = payload["components"][0]["effects"]["html"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Livewire response did not include availability HTML") from exc

    if not isinstance(availability_html, str):
        raise TypeError("Livewire availability HTML must be a string")

    return availability_html


def parse_availability_table(availability_html: str, scraped_at: datetime) -> list[ParkingLot]:
    parser = AvailabilityTableParser()
    parser.feed(availability_html)

    lots = [
        ParkingLot.from_row(row_number, row, scraped_at)
        for row_number, row in enumerate(parser.rows, start=1)
    ]
    if not lots:
        raise ValueError("No parking lots found in availability table")

    return lots


def fetch_parking_lots() -> list[ParkingLot]:
    url = os.environ.get("SMF_PARKING_URL", DEFAULT_PARKING_URL)
    insecure_tls = env_bool("SMF_PARKING_INSECURE_TLS")
    timeout = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "10"))

    session = requests.Session()
    response = session.get(url, verify=not insecure_tls, timeout=timeout)
    response.raise_for_status()

    page = parse_parking_page(response.text)
    availability_html = load_availability_html(
        session=session,
        parking_url=url,
        page=page,
        timeout=timeout,
        verify_tls=not insecure_tls,
    )

    scraped_at = datetime.now(timezone.utc)
    return parse_availability_table(availability_html, scraped_at)


def build_snapshot(parking_lots: list[ParkingLot]) -> dict[str, Any]:
    if not parking_lots:
        scraped_at = datetime.now(timezone.utc)
    else:
        scraped_at = parking_lots[0].scraped_at

    return {
        "scraped_at": scraped_at.isoformat(),
        "lots": [lot.to_json_dict() for lot in parking_lots],
    }


def write_json_data(snapshot: dict[str, Any]) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    OCCUPANCY_DIR.mkdir(parents=True, exist_ok=True)

    latest_text = json.dumps(snapshot, separators=(",", ":"), sort_keys=True)
    LATEST_PATH.write_text(f"{latest_text}\n", encoding="utf-8")

    scraped_at = datetime.fromisoformat(snapshot["scraped_at"])
    history_path = OCCUPANCY_DIR / f"{scraped_at.date().isoformat()}.jsonl"
    with history_path.open("a", encoding="utf-8") as history_file:
        history_file.write(f"{latest_text}\n")

    return history_path


def load_occupancy_history() -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    if not OCCUPANCY_DIR.exists():
        return snapshots

    for path in sorted(OCCUPANCY_DIR.glob("*.jsonl")):
        with path.open(encoding="utf-8") as history_file:
            for line_number, line in enumerate(history_file, start=1):
                if not line.strip():
                    continue
                try:
                    snapshot = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSONL") from exc
                if isinstance(snapshot, dict) and isinstance(snapshot.get("lots"), list):
                    snapshots.append(snapshot)

    return sorted(snapshots, key=lambda snapshot: snapshot.get("scraped_at", ""))


def load_lot_config() -> dict[str, Any]:
    if not LOT_CONFIG_PATH.exists():
        return {"lot_name_aliases": {}, "lots": {}}

    config = json.loads(LOT_CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise TypeError(f"{LOT_CONFIG_PATH} must contain a JSON object")

    return config


def canonical_lot_name(name: Any, lot_id: Any, aliases: dict[str, str]) -> str:
    raw_name = str(name or f"Lot {lot_id}").strip()
    return aliases.get(raw_name.lower(), raw_name)


def int_value(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def daily_max_rate(pricing: Any) -> float | None:
    match = re.search(r"\$(\d+(?:\.\d+)?)\s*/\s*day\s+max", str(pricing), re.IGNORECASE)
    return float(match.group(1)) if match else None


def build_chart_data(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    lot_config = load_lot_config()
    aliases = {
        str(alias).lower(): str(canonical)
        for alias, canonical in lot_config.get("lot_name_aliases", {}).items()
    }
    configured_lots = lot_config.get("lots", {})
    capacities = {
        str(name): lot.get("capacity")
        for name, lot in configured_lots.items()
        if isinstance(lot, dict) and isinstance(lot.get("capacity"), int)
    }
    lot_names: list[str] = []
    seen_lots: set[str] = set()
    points: list[dict[str, Any]] = []
    latest_pricing: dict[str, str] = {}
    lot_daily_max_rates: dict[str, float] = {}

    for snapshot in snapshots:
        lots_by_name: dict[str, int | None] = {}
        occupied_by_name: dict[str, int | None] = {}
        capacities_by_name: dict[str, int | None] = {}
        total_free_spaces = 0
        total_occupied_spaces = 0
        total_capacity = 0

        for lot in snapshot.get("lots", []):
            if not isinstance(lot, dict):
                continue

            name = canonical_lot_name(lot.get("name"), lot.get("id", ""), aliases)
            if not name:
                continue

            pricing = str(lot.get("pricing") or "").strip()
            if pricing:
                latest_pricing[name] = pricing
                rate = daily_max_rate(pricing)
                if rate is not None:
                    lot_daily_max_rates[name] = rate

            free_spaces = int_value(lot.get("free_spaces"))
            capacity = capacities.get(name)
            occupied_spaces = int_value(lot.get("occupied_spaces"))
            if occupied_spaces is None and capacity is not None and free_spaces is not None:
                occupied_spaces = max(capacity - free_spaces, 0)

            lots_by_name[name] = free_spaces
            occupied_by_name[name] = occupied_spaces
            capacities_by_name[name] = capacity
            if free_spaces is not None:
                total_free_spaces += free_spaces
            if occupied_spaces is not None:
                total_occupied_spaces += occupied_spaces
            if capacity is not None:
                total_capacity += capacity

            if name not in seen_lots:
                seen_lots.add(name)
                lot_names.append(name)

        points.append(
            {
                "scraped_at": snapshot.get("scraped_at"),
                "total_free_spaces": total_free_spaces,
                "total_occupied_spaces": total_occupied_spaces,
                "total_capacity": total_capacity,
                "lots": lots_by_name,
                "occupied_lots": occupied_by_name,
                "capacities": capacities_by_name,
            }
        )

    totals = [point["total_free_spaces"] for point in points]
    occupied_totals = [point["total_occupied_spaces"] for point in points]
    first_total = totals[0] if totals else 0
    latest_total = totals[-1] if totals else 0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lot_daily_max_rates": lot_daily_max_rates,
        "lot_names": lot_names,
        "lot_pricing": latest_pricing,
        "points": points,
        "summary": {
            "snapshot_count": len(points),
            "first_total": first_total,
            "latest_total": latest_total,
            "net_change": latest_total - first_total,
            "minimum_total": min(totals) if totals else 0,
            "maximum_total": max(totals) if totals else 0,
            "total_range": (max(totals) - min(totals)) if totals else 0,
            "latest_occupied_total": occupied_totals[-1] if occupied_totals else 0,
            "capacity_total": points[-1]["total_capacity"] if points else 0,
        },
    }


def build_static_report_html(chart_data: dict[str, Any]) -> str:
    chart_json = json.dumps(chart_data, separators=(",", ":"), sort_keys=True)
    chart_json_script = chart_json.replace("</", "<\\/")
    template = REPORT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__CHART_DATA_JSON__", chart_json_script)


def write_static_report() -> Path:
    chart_data = build_chart_data(load_occupancy_history())
    STATIC_REPORT_PATH.write_text(build_static_report_html(chart_data), encoding="utf-8")
    return STATIC_REPORT_PATH


def main() -> None:
    parking_lots = fetch_parking_lots()
    snapshot = build_snapshot(parking_lots)
    history_path = write_json_data(snapshot)
    report_path = write_static_report()
    print(
        f"Wrote {len(parking_lots)} parking lots to "
        f"{LATEST_PATH}, {history_path}, and {report_path}"
    )


if __name__ == "__main__":
    main()
