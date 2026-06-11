from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import requests


DEFAULT_COUNT_URL = "https://smf-count.ipparkingna.com/live-count"
DATA_DIR = Path("data")
LATEST_PATH = DATA_DIR / "latest.json"
OCCUPANCY_DIR = DATA_DIR / "occupancy"


@dataclass(frozen=True)
class ParkingLot:
    scraped_at: datetime
    id: int
    name: str
    free_spaces: int
    occupied_spaces: int
    total_capacity: int

    @classmethod
    def from_dict(cls, data: dict[str, Any], scraped_at: datetime) -> "ParkingLot":
        return cls(
            scraped_at=scraped_at,
            id=int(data["id"]),
            name=str(data["name"]),
            free_spaces=int(data["free_spaces"]),
            occupied_spaces=int(data["occupied_spaces"]),
            total_capacity=int(data["total_capacity"]),
        )

    def to_json_dict(self) -> dict[str, Any]:
        lot = asdict(self)
        lot.pop("scraped_at")
        return lot


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def fetch_parking_lots() -> list[ParkingLot]:
    url = os.environ.get("SMF_COUNT_URL", DEFAULT_COUNT_URL)
    insecure_tls = env_bool("SMF_COUNT_INSECURE_TLS")
    timeout = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "10"))

    response = requests.get(url, verify=not insecure_tls, timeout=timeout)
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, list):
        raise TypeError("Expected live-count response to be a JSON list")

    scraped_at = datetime.now(timezone.utc)
    return [ParkingLot.from_dict(item, scraped_at) for item in payload]


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


def main() -> None:
    parking_lots = fetch_parking_lots()
    snapshot = build_snapshot(parking_lots)
    history_path = write_json_data(snapshot)
    print(
        f"Wrote {len(parking_lots)} parking lots to "
        f"{LATEST_PATH} and {history_path}"
    )


if __name__ == "__main__":
    main()
