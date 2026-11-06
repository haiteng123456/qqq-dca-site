import contextlib
import copy
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import update_qqq as updater


class MarketDateTests(unittest.TestCase):
    def test_excludes_live_session_and_handles_both_time_offsets(self):
        for timestamp, expected in (
            ("2026-11-06T20:59:00+00:00", "2026-11-05"),
            ("2026-11-06T21:15:00+00:00", "2026-11-06"),
            ("2026-07-31T20:14:00+00:00", "2026-07-30"),
            ("2026-07-31T20:15:00+00:00", "2026-07-31"),
        ):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(updater.latest_completed_market_date(datetime.fromisoformat(timestamp)).isoformat(), expected)


class PartialUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads(updater.MARKET_JSON.read_text(encoding="utf-8"))

    def run_update(self, failure=False, changed=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            market = root / "market_dca.json"
            before = json.dumps(self.original, ensure_ascii=False).encode()
            market.write_bytes(before)

            def fake_update(meta, **kwargs):
                symbol = meta["symbol"]
                if failure and symbol == "SPY":
                    raise OSError("Temporary provider failure")
                summary = copy.deepcopy(next(item for item in self.original["symbols"] if item["symbol"] == symbol))
                if changed:
                    summary["testRefresh"] = True
                rows = [{"date": row[0], "compact": row} for row in self.original["series"][symbol]]
                return summary, rows, [], None

            with patch.multiple(updater, MARKET_JSON=market, MARKET_JS=root / "market_dca.js", PUBLIC_DATA_DIR=root, DATA_DIR=root / "data"), \
                    patch.object(updater, "update_symbol", side_effect=fake_update) as update, \
                    patch.object(updater, "compact_public_rows", side_effect=lambda rows, **kwargs: [row["compact"] for row in rows]), \
                    patch.object(updater, "write_incremental_public_data"), \
                    patch.object(updater, "write_qqq_compat"), \
                    patch("sys.argv", ["update_qqq.py", "--symbols", "QQQ,SPY", "--no-fetch"]), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = updater.main()
            return result, update.call_args_list, json.loads(market.read_bytes()), market.read_bytes() == before

    def test_updates_only_indices_and_preserves_every_other_symbol(self):
        result, calls, after, unchanged = self.run_update()
        self.assertEqual(result, 0)
        self.assertEqual([call.args[0]["symbol"] for call in calls], ["QQQ", "SPY"])
        for item in self.original["symbols"]:
            if item["symbol"] not in ("QQQ", "SPY"):
                actual = next(meta for meta in after["symbols"] if meta["symbol"] == item["symbol"])
                self.assertEqual(actual, item)
                self.assertEqual(after["series"][item["symbol"]], self.original["series"][item["symbol"]])

    def test_one_failed_index_does_not_replace_public_data(self):
        result, _, _, unchanged = self.run_update(failure=True)
        self.assertEqual(result, 1)
        self.assertTrue(unchanged)

    def test_no_new_prices_keeps_snapshot_unchanged(self):
        result, _, _, unchanged = self.run_update(changed=False)
        self.assertEqual(result, 0)
        self.assertTrue(unchanged)


if __name__ == "__main__":
    unittest.main()
