import os
import threading

import requests


class ProxyPool:
    def __init__(self, proxy_file=None, proxy_api=None):
        self.proxies = []
        self._lock = threading.Lock()
        self._index = 0
        self._health = {}
        if proxy_file and os.path.exists(proxy_file):
            with open(proxy_file) as f:
                self.proxies = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            print(f"  [+] Loaded {len(self.proxies)} proxies from {proxy_file}")
        if proxy_api:
            try:
                resp = requests.get(proxy_api, timeout=10)
                if resp.status_code == 200:
                    new_proxies = [p.strip() for p in resp.text.splitlines() if p.strip()]
                    self.proxies.extend(new_proxies)
                    print(f"  [+] Loaded {len(new_proxies)} proxies from API")
            except Exception as e:
                print(f"  [!] Failed to fetch proxies from API: {e}")

    def get_proxy(self):
        if not self.proxies:
            return None
        with self._lock:
            proxy = self.proxies[self._index % len(self.proxies)]
            self._index += 1
            return proxy

    def mark_bad(self, proxy):
        with self._lock:
            self._health[proxy] = self._health.get(proxy, 0) + 1
            if self._health[proxy] > 3 and proxy in self.proxies:
                self.proxies.remove(proxy)

    def size(self):
        return len(self.proxies)
