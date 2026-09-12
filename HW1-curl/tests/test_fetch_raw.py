import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
from http_client import HttpClient

BASE_URL = "https://jsonplaceholder.typicode.com"


class TestHttpClient(unittest.TestCase):
    def setUp(self):
        self.client = HttpClient(BASE_URL)

    def test_get_posts_returns_200_and_array(self):
        resp = self.client.get("/posts")
        self.assertEqual(resp["status"], 200)
        body = resp["body"].decode("utf-8")
        self.assertTrue(body.startswith("["), f"Expected array, got: {body[:50]}")
        self.assertIn("userId", body)
        self.assertIn("title", body)
        self.assertIn("content-type", resp["headers"])
        self.assertIn("application/json", resp["headers"]["content-type"])

    def test_get_single_post_has_id_1(self):
        resp = self.client.get("/posts/1")
        self.assertEqual(resp["status"], 200)
        body = resp["body"].decode("utf-8")
        self.assertIn('"id": 1', body)
        self.assertIn('"userId"', body)

    def test_get_404(self):
        resp = self.client.get("/posts/9999")
        self.assertEqual(resp["status"], 404)

    def test_get_users_has_email(self):
        resp = self.client.get("/users")
        self.assertEqual(resp["status"], 200)
        body = resp["body"].decode("utf-8")
        self.assertIn('"email"', body)
        self.assertIn("@", body)

    def test_chunked_or_content_length_decoded(self):
        resp = self.client.get("/posts")
        body = resp["body"].decode("utf-8")
        self.assertGreater(len(body), 1000, "Body too short, chunked decode may be broken")


class TestFetchRawCLI(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "fetch_raw.py"), *args],
            capture_output=True,
        )

    def test_cli_posts(self):
        r = self.run_cli("posts")
        self.assertEqual(r.returncode, 0, msg=r.stderr.decode())
        self.assertIn(b"userId", r.stdout)

    def test_cli_posts_1(self):
        r = self.run_cli("posts", "1")
        self.assertEqual(r.returncode, 0, msg=r.stderr.decode())
        self.assertIn(b'"id": 1', r.stdout)

    def test_cli_404_exits_nonzero(self):
        r = self.run_cli("posts", "9999")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"404", r.stderr)

    def test_cli_no_args_shows_usage(self):
        r = self.run_cli()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"Usage", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
