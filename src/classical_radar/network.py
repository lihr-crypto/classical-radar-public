"""Bounded public-page reads. Redirects stay on registered HTTPS host aliases."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

UA = "ClassicalRadarPOC/0.1 (+https://github.com/lihr-crypto/classical-radar-public; low-volume source evaluation)"


class FetchError(RuntimeError):
    pass


class Reader:
    def __init__(self, raw_dir: Path, transport=None, interval: float = 2.0):
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(headers={"User-Agent": UA}, timeout=25, follow_redirects=False, transport=transport)
        self.interval = interval
        self.last: dict[str, float] = {}
        self.stopped: set[str] = set()

    def close(self):
        self.client.close()

    def get(self, url: str, host: str) -> tuple[str, dict]:
        response, original = self._fetch(url, host)
        digest = sha256(response.content).hexdigest()
        (self.raw_dir / f"{digest}.html").write_bytes(response.content)
        return response.text, self._meta(original, response, digest)

    def get_bytes(self, url: str, host: str, max_bytes: int = 5_000_000) -> tuple[bytes, dict]:
        """The same bounded read for a file that is not text (the season PDF): the raw bytes, refused above ``max_bytes``."""
        response, original = self._fetch(url, host)
        if len(response.content) > max_bytes:
            raise FetchError(f"file larger than {max_bytes} bytes")
        digest = sha256(response.content).hexdigest()
        (self.raw_dir / f"{digest}.bin").write_bytes(response.content)
        return response.content, self._meta(original, response, digest)

    @staticmethod
    def _meta(original: str, response, digest: str) -> dict:
        return {
            "requested_url": original, "url": str(response.url),
            "status": response.status_code, "bytes": len(response.content),
            "sha256": digest, "fetched_at": datetime.now(timezone.utc).isoformat(),
            "content_type": response.headers.get("content-type"),
            "etag": response.headers.get("etag"), "last_modified": response.headers.get("last-modified"),
        }

    def _fetch(self, url: str, host: str):
        allowed = {host, host.removeprefix("www."), "www." + host.removeprefix("www.")}
        original = url
        for _ in range(5):
            p = urlsplit(url)
            if p.scheme != "https" or p.hostname not in allowed or p.port not in (None, 443) or p.username or p.password:
                raise FetchError("URL/redirect outside registered HTTPS hosts")
            if host in self.stopped:
                raise FetchError("source paused after HTTP access restriction")
            time.sleep(max(0.0, self.interval - (time.monotonic() - self.last.get(host, 0))))
            self.last[host] = time.monotonic()
            try:
                response = self.client.get(url)
            except httpx.TransportError as exc:  # reset/timeout: a transient fault, not an access restriction
                raise FetchError(f"transport error: {type(exc).__name__}") from exc
            if response.status_code in (401, 403, 429):
                self.stopped.add(host)
                raise FetchError(f"HTTP {response.status_code}; source paused; Retry-After={response.headers.get('retry-after')}")
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            if response.status_code >= 400 and response.status_code != 404:
                raise FetchError(f"HTTP {response.status_code}")
            return response, original
        raise FetchError("too many redirects")


def robots_allowed(text: str, status: int, url: str) -> bool:
    if status == 404:
        return True  # Missing robots is not a positive grant of reuse permission.
    if status != 200:
        return False
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(UA, url)
