"""Small, careful GitHub REST client: auth, pagination, rate-limit handling."""
import os
import time
from typing import Iterator, Optional

import requests

API = "https://api.github.com"
MAX_RATE_WAIT_SECONDS = 120  # if the reset is further away than this, stop and tell the user


class GitHubError(Exception):
    pass


class GitHubClient:
    def __init__(self, token: Optional[str] = None, session=None, sleep=time.sleep):
        self.token = token or os.getenv("GITHUB_TOKEN") or None
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "CodeWhy-HackFront",
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
        self._sleep = sleep
        self.requests_made = 0

    def _url(self, path_or_url: str) -> str:
        return path_or_url if path_or_url.startswith("http") else f"{API}{path_or_url}"

    def get(self, path_or_url: str, params: Optional[dict] = None):
        url = self._url(path_or_url)
        for attempt in range(4):
            resp = self.session.get(url, params=params, timeout=30)
            self.requests_made += 1
            code = resp.status_code
            if code == 200:
                return resp
            if code in (403, 429):
                remaining = resp.headers.get("X-RateLimit-Remaining")
                retry_after = resp.headers.get("Retry-After")
                if remaining == "0" or retry_after or code == 429:
                    if retry_after:
                        wait = int(retry_after)
                    else:
                        reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
                        wait = max(reset - int(time.time()), 1)
                    if wait > MAX_RATE_WAIT_SECONDS:
                        raise GitHubError(
                            f"GitHub rate limit hit; resets in ~{wait // 60} min. "
                            "Set GITHUB_TOKEN in .env to get a much higher limit."
                        )
                    self._sleep(wait + 1)
                    continue
            if code == 404:
                raise GitHubError(f"Not found: {url}")
            if code >= 500:
                self._sleep(2**attempt)
                continue
            raise GitHubError(f"GitHub returned {code} for {url}: {resp.text[:200]}")
        raise GitHubError(f"Giving up after retries: {url}")

    def paginate(self, path: str, params: Optional[dict] = None, max_items: Optional[int] = None) -> Iterator[dict]:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        url, first, count = path, True, 0
        while url:
            resp = self.get(url, params if first else None)
            first = False
            for item in resp.json():
                yield item
                count += 1
                if max_items is not None and count >= max_items:
                    return
            url = resp.links.get("next", {}).get("url")
