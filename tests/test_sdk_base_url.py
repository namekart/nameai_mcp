import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk-python" / "src"))

from nameai import NameAI  # noqa: E402


class BaseUrlValidation(unittest.TestCase):
    def test_accepts_http_and_https(self):
        self.assertEqual(NameAI().base_url, "https://name.ai")
        self.assertEqual(NameAI("http://localhost:3000/").base_url, "http://localhost:3000")

    def test_rejects_non_http_schemes(self):
        for bad in ("file:///etc/passwd", "ftp://name.ai", "name.ai", "https://"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                NameAI(bad)


if __name__ == "__main__":
    unittest.main()
