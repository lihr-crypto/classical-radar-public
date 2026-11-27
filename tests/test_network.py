from pathlib import Path
import tempfile
import unittest

import httpx
from classical_radar.network import FetchError,Reader,robots_allowed


class NetworkTests(unittest.TestCase):
    def test_robots_disallow_and_missing(self):
        self.assertFalse(robots_allowed("User-agent: *\nDisallow: /private/",200,"https://example.com/private/event"))
        self.assertTrue(robots_allowed("",404,"https://example.com/concert/"))
        self.assertFalse(robots_allowed("",503,"https://example.com/concert/"))

    def test_restriction_pauses_entire_source_without_retry(self):
        for status in [401,403,429]:
            calls=[]
            def handle(request):
                calls.append(str(request.url));return httpx.Response(status,headers={"Retry-After":"600"})
            with self.subTest(status=status),tempfile.TemporaryDirectory() as path:
                reader=Reader(Path(path),httpx.MockTransport(handle),interval=0)
                try:
                    for url in ["https://example.com/a","https://example.com/b"]:
                        with self.assertRaises(FetchError):reader.get(url,"example.com")
                    self.assertEqual(len(calls),1)
                finally:reader.close()

    def test_redirect_is_revalidated_before_request(self):
        calls=[]
        def handle(request):
            calls.append(str(request.url));return httpx.Response(302,headers={"Location":"http://127.0.0.1/private"})
        with tempfile.TemporaryDirectory() as path:
            reader=Reader(Path(path),httpx.MockTransport(handle),interval=0)
            try:
                with self.assertRaises(FetchError):reader.get("https://example.com/a","example.com")
                self.assertEqual(len(calls),1)
            finally:reader.close()

    def test_transport_reset_is_a_fetch_error_and_does_not_pause_source(self):
        def handle(request):
            raise httpx.ConnectError("reset",request=request)
        with tempfile.TemporaryDirectory() as path:
            reader=Reader(Path(path),httpx.MockTransport(handle),interval=0)
            try:
                with self.assertRaisesRegex(FetchError,"transport error"):reader.get("https://example.com/a","example.com")
                self.assertNotIn("example.com",reader.stopped)
            finally:reader.close()


if __name__=="__main__":unittest.main()
