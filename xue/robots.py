import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


class RobotsManager:
    def __init__(self, session, timeout=10, ttl_secs=3600):
        self.session = session
        self.timeout = timeout
        self.ttl_secs = ttl_secs
        self._cache = {}
        self._lock = threading.Lock()

    def _get_robots_url(self, url):
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _fetch_rules(self, url):
        robots_url = self._get_robots_url(url)
        rp = RobotFileParser()
        try:
            resp = self.session.get(robots_url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.parse([])
        except Exception:
            rp.parse([])
        return rp

    def is_allowed(self, url):
        domain = urlparse(url).netloc
        with self._lock:
            entry = self._cache.get(domain)
            if entry and (time.time() - entry["fetched_at"]) < self.ttl_secs:
                return entry["parser"].can_fetch("*", url)
        rp = self._fetch_rules(url)
        with self._lock:
            if domain not in self._cache:
                self._cache[domain] = {"parser": rp, "fetched_at": time.time()}
            return self._cache[domain]["parser"].can_fetch("*", url)
