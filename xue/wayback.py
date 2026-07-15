import threading


class WaybackLookup:
    AVAILABILITY_URL = "http://archive.org/wayback/available"

    def __init__(self, session, timeout=10):
        self.session = session
        self.timeout = timeout
        self._cache = {}
        self._lock = threading.Lock()
        self.hit_count = 0
        self.miss_count = 0

    def lookup(self, url):
        with self._lock:
            if url in self._cache:
                return self._cache[url]
        try:
            resp = self.session.get(self.AVAILABILITY_URL, params={"url": url}, timeout=self.timeout)
            data = resp.json()
            archived = data.get("archived_snapshots", {}).get("closest", {})
            result = archived.get("url") if archived.get("available") else None
        except Exception:
            result = None
        with self._lock:
            self._cache[url] = result
            if result:
                self.hit_count += 1
            else:
                self.miss_count += 1
        return result
