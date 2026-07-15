import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class DomainBudget:
    pages: int = 0
    start_time: float = 0.0
    total_bytes: int = 0


class CrawlBudget:
    def __init__(self, max_pages_per_domain: int = 0, max_time_per_domain: int = 0,
                 max_size_per_domain: int = 0):
        self.max_pages = max_pages_per_domain
        self.max_time = max_time_per_domain
        self.max_size = max_size_per_domain
        self._domains: dict[str, DomainBudget] = defaultdict(DomainBudget)
        self._lock = threading.Lock()

    def check_url(self, url: str) -> bool:
        domain = urlparse(url).netloc
        with self._lock:
            if domain not in self._domains:
                self._domains[domain] = DomainBudget(start_time=time.time())
            return self._within_budget(domain)

    def record_page(self, url: str, size_bytes: int = 0):
        domain = urlparse(url).netloc
        with self._lock:
            if domain not in self._domains:
                self._domains[domain] = DomainBudget(start_time=time.time())
            db = self._domains[domain]
            db.pages += 1
            db.total_bytes += size_bytes

    def _within_budget(self, domain: str) -> bool:
        db = self._domains[domain]
        if self.max_pages > 0 and db.pages >= self.max_pages:
            return False
        if self.max_time > 0 and (time.time() - db.start_time) >= self.max_time:
            return False
        if self.max_size > 0 and db.total_bytes >= self.max_size:
            return False
        return True

    def status(self, url: str) -> dict:
        domain = urlparse(url).netloc
        with self._lock:
            db = self._domains.get(domain)
            if db is None:
                return {"pages": 0, "elapsed": 0.0, "bytes": 0}
            return {
                "pages": db.pages,
                "elapsed": time.time() - db.start_time,
                "bytes": db.total_bytes,
            }
