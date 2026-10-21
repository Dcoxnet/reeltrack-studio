"""Smoke checks for the local API; no live network calls."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import api

class TestAPI(unittest.TestCase):
    def test_counts(self):
        result = api.count_status([
            {"status": "DOWNLOADED", "artist": "A", "song": "B"},
            {"status": "CHECK_MANUALLY", "artist": "C", "song": "D"},
            {"status": "NOT_RECOGNIZED", "artist": "", "song": ""},
        ])
        self.assertEqual(result["downloaded"], 1)
        self.assertEqual(result["manual"], 1)
        self.assertEqual(result["recognized"], 2)
    def test_link_re(self):
        self.assertEqual(api.LINK_RE.search("https://www.instagram.com/reel/DedAC7PKzmZ/?a=b").group(1), "DedAC7PKzmZ")
    def test_csv_records(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"reels.txt").write_text("https://www.instagram.com/reel/aaa/\n", encoding="utf-8")
            with patch.object(api, "REELS", root/"reels.txt"), patch.object(api, "RESULTS", root/"results.csv"):
                self.assertEqual(api.read_records()[0]["n"], 1)

if __name__ == "__main__": unittest.main()
