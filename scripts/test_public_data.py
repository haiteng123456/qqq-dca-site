import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import update_qqq


class PublicDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(update_qqq.MARKET_JSON.read_text(encoding="utf-8"))

    def test_priority_is_small_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(update_qqq, "PUBLIC_DATA_DIR", root):
                update_qqq.write_incremental_public_data(self.payload)
            priority = json.loads((root / "market_priority.json").read_text())
            self.assertEqual([item["symbol"] for item in priority["symbols"]], ["QQQ", "SPY"])
            self.assertEqual(set(priority["series"]), {"QQQ", "SPY"})
            self.assertLess((root / "market_priority.json").stat().st_size, 100_000)
            summary_path = root / priority["summaryPath"].removeprefix("./data/")
            summary = json.loads(summary_path.read_text())
            self.assertEqual(len(summary["symbols"]), len(self.payload["symbols"]))
            self.assertEqual(summary["updatedAt"], self.payload["updatedAt"])
            self.assertNotIn("series", summary)
            self.assertEqual([item["symbol"] for item in summary["symbols"][:2]], ["QQQ", "SPY"])
            for symbol, original_rows in self.payload["series"].items():
                path = root / summary["historyPaths"][symbol].removeprefix("./data/")
                data = path.read_bytes()
                history = json.loads(data)
                self.assertEqual(history["symbol"], symbol)
                self.assertEqual(history["rows"], original_rows)
                self.assertIn(hashlib.sha256(data).hexdigest()[:16], path.name)
                if symbol in priority["series"]:
                    self.assertEqual(priority["series"][symbol], original_rows[-270:])

    def test_single_symbol_update_remains_loadable(self):
        limited = {
            **self.payload,
            "symbols": [item for item in self.payload["symbols"] if item["symbol"] == "NVDA"],
            "series": {"NVDA": self.payload["series"]["NVDA"]},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(update_qqq, "PUBLIC_DATA_DIR", root):
                update_qqq.write_incremental_public_data(limited)
            priority = json.loads((root / "market_priority.json").read_text())
            self.assertEqual([item["symbol"] for item in priority["symbols"]], ["NVDA"])
            self.assertEqual(priority["series"]["NVDA"], limited["series"]["NVDA"][-270:])

    def test_index_history_starts_in_2000_with_a_full_dca_window(self):
        for symbol in ("QQQ", "SPY"):
            rows = self.payload["series"][symbol]
            self.assertEqual(rows[0][0], "2000-01-03")
            self.assertGreater(len(rows), 26 * 240)
            prices = update_qqq.load_prices(update_qqq.price_path(symbol))
            first = next(i for i, price in enumerate(prices) if price.date == rows[0][0])
            window = prices[first - 179:first + 1]
            self.assertEqual(len(window), 180)
            self.assertEqual(rows[0][1], window[0].date)
            self.assertAlmostEqual(rows[0][4], 180 / sum(1 / price.close for price in window), places=3)
            meta = next(item for item in self.payload["symbols"] if item["symbol"] == symbol)
            self.assertEqual(rows[-1][0], meta["latest"]["date"])


if __name__ == "__main__":
    unittest.main()
