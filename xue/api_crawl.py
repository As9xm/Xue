import json
import re
import threading


class ApiCrawler:
    JSON_PATTERNS = [
        re.compile(r'"(items|results|data|records|entries)"\s*:\s*\['),
        re.compile(r'"(next_page|next_cursor|next_token|page_info)"\s*:\s*'),
        re.compile(r'"(total|count|total_count|total_results)"\s*:\s*\d+'),
    ]

    def __init__(self):
        self.api_endpoints = []
        self._lock = threading.Lock()

    def is_api_response(self, content_type, text):
        if "application/json" in content_type:
            return True
        if "text/plain" in content_type:
            try:
                json.loads(text[:1024])
                return True
            except (json.JSONDecodeError, ValueError):
                pass
        return False

    def detect_pagination(self, text):
        patterns_found = 0
        for pattern in self.JSON_PATTERNS:
            if pattern.search(text):
                patterns_found += 1
        return patterns_found >= 2

    def record_endpoint(self, url, has_pagination):
        with self._lock:
            self.api_endpoints.append({"url": url, "has_pagination": has_pagination})
