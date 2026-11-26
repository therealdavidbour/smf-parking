from datetime import datetime, timezone
import json
import re
import unittest

import query


class GarageReportTests(unittest.TestCase):
    def test_garage_rename_preserves_history_and_capacity(self):
        snapshots = [
            {
                "scraped_at": f"2026-11-{day:02d}T12:00:00+00:00",
                "lots": [
                    {
                        "id": 1,
                        "name": name,
                        "free_spaces": 1700,
                        "pricing": "$2 /30min | $28 /day max",
                    }
                ],
            }
            for day, name in enumerate(["Garage", "Parking Garage", "Garage 1"], start=24)
        ]

        report = query.build_static_report_html(query.build_chart_data(snapshots))
        match = re.search(
            r'<script id="chart-data" type="application/json">(.*?)</script>', report
        )
        self.assertIsNotNone(match)
        data = json.loads(match.group(1))
        self.assertEqual(data["lot_names"], ["Garage"])
        for point in data["points"]:
            self.assertEqual(point["lots"], {"Garage": 1700})
            self.assertEqual(point["capacities"], {"Garage": 5230})
            self.assertEqual(point["occupied_lots"], {"Garage": 3530})
        self.assertEqual(data["lot_daily_max_rates"], {"Garage": 28})

    def test_new_table_keeps_garages_separate_and_open_count_unknown(self):
        lots = query.parse_availability_table(
            """
            <table>
              <thead><tr><th>Lot</th><th>Open Spaces</th><th>Pricing</th></tr></thead>
              <tbody>
                <tr><td>Garage 1</td><td>1,741</td>
                  <td><span><strong>$2</strong>&nbsp;/30min</span>
                    <span>|</span><span><strong>$28</strong>&nbsp;/day max</span></td></tr>
                <tr><td>Garage 2</td><td>Open</td><td>$2 /30min | $28 /day max</td></tr>
                <tr><td>Daily A</td><td>266</td><td>$2 /30min | $19 /day max</td></tr>
                <tr><td>West Economy Lot</td><td>Closed</td><td>$14 /day max</td></tr>
              </tbody>
            </table>
            """,
            datetime(2026, 11, 26, tzinfo=timezone.utc),
        )
        self.assertEqual(lots[0].free_spaces, 1741)
        self.assertEqual(lots[0].pricing, "$2 /30min | $28 /day max")
        self.assertEqual(lots[1].status, "open")
        self.assertIsNone(lots[1].free_spaces)
        self.assertEqual(lots[3].status, "closed")
        data = query.build_chart_data([query.build_snapshot(lots)])
        point = data["points"][0]
        self.assertEqual(data["lot_names"], ["Garage", "Garage 2", "Daily A", "West Economy Lot"])
        self.assertEqual(point["capacities"]["Garage 2"], 5500)
        self.assertIsNone(point["lots"]["Garage 2"])
        self.assertIsNone(point["occupied_lots"]["Garage 2"])
        self.assertEqual(point["occupied_lots"]["Garage"], 3489)
        self.assertEqual(point["lots"]["Daily A"], 266)
        self.assertEqual(point["total_free_spaces"], 2007)


if __name__ == "__main__":
    unittest.main()
