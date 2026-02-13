#!/usr/bin/env python3
"""
Xue — Continuous Internet Crawler with Tor Support & Aggregator

Crawls the web starting from a seed URL, following every link it discovers.
Supports clearnet and Tor .onion services seamlessly.
Runs indefinitely until stopped with CTRL+C.

Usage:
    python xue.py -u https://example.com
    python xue.py -u http://exampleonion.onion --tor-proxy socks5h://127.0.0.1:9050
"""

import argparse
import collections
import json
import os
import platform
import random
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urldefrag

try:
    import requests
    from requests.adapters import HTTPAdapter
except ImportError:
    print("[!] Missing dependency: requests")
    print("    pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup, SoupStrainer
except ImportError:
    print("[!] Missing dependency: beautifulsoup4")
    print("    pip install beautifulsoup4")
    sys.exit(1)

import re

try:
    import socks  # PySocks
except ImportError:
    socks = None

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# ─── ANSI Colors ────────────────────────────────────────────────────────────────

class C:
    RST   = "\033[0m"
    BOLD  = "\033[1m"
    DIM   = "\033[2m"
    RED   = "\033[91m"
    GREEN = "\033[92m"
    YELLOW= "\033[93m"
    BLUE  = "\033[94m"
    MAGENTA="\033[95m"
    CYAN  = "\033[96m"
    WHITE = "\033[97m"
    GRAY  = "\033[90m"


BANNER = f"""{C.CYAN}{C.BOLD}
  ██╗  ██╗██╗   ██╗███████╗
  ╚██╗██╔╝██║   ██║██╔════╝
   ╚███╔╝ ██║   ██║█████╗  
   ██╔██╗ ██║   ██║██╔══╝  
  ██╔╝ ██╗╚██████╔╝███████╗
  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝{C.RST}
  {C.DIM}Continuous Internet Crawler · Tor Enabled{C.RST}
"""


# ─── System Profiler ────────────────────────────────────────────────────────────

class SystemProfiler:
    """
    Detects system specs and recommends a safe thread count.
    Tests CPU cores, available RAM, and optionally network throughput.
    """

    def __init__(self):
        self.cpu_cores = os.cpu_count() or 2
        self.cpu_threads = self.cpu_cores  # logical cores
        self.total_ram_mb = 0
        self.available_ram_mb = 0
        self.cpu_usage_pct = 0.0
        self.os_name = platform.system()
        self.os_version = platform.version()
        self.python_version = platform.python_version()

        self._detect_specs()

    def _detect_specs(self):
        """Gather system information."""
        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            self.total_ram_mb = mem.total // (1024 * 1024)
            self.available_ram_mb = mem.available // (1024 * 1024)
            self.cpu_usage_pct = psutil.cpu_percent(interval=0.5)
            self.cpu_threads = psutil.cpu_count(logical=True) or self.cpu_cores
            self.cpu_cores = psutil.cpu_count(logical=False) or self.cpu_cores
        else:
            # Fallback: try to estimate RAM on Windows/Linux
            try:
                if sys.platform == "win32":
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    class MEMORYSTATUSEX(ctypes.Structure):
                        _fields_ = [
                            ("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                        ]
                    stat = MEMORYSTATUSEX()
                    stat.dwLength = ctypes.sizeof(stat)
                    kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                    self.total_ram_mb = stat.ullTotalPhys // (1024 * 1024)
                    self.available_ram_mb = stat.ullAvailPhys // (1024 * 1024)
                elif sys.platform.startswith("linux"):
                    with open("/proc/meminfo") as f:
                        lines = f.readlines()
                    for line in lines:
                        if line.startswith("MemTotal:"):
                            self.total_ram_mb = int(line.split()[1]) // 1024
                        elif line.startswith("MemAvailable:"):
                            self.available_ram_mb = int(line.split()[1]) // 1024
            except Exception:
                self.total_ram_mb = 4096  # assume 4GB
                self.available_ram_mb = 2048

    def recommend_threads(self):
        """
        Recommend thread count based on system resources.
        
        Each crawler thread uses ~5-15 MB of RAM (session + buffers + HTML parsing).
        We cap at a safe percentage of available resources.
        
        Returns: (recommended_threads, max_safe_threads, reason)
        """
        # Base: 2x CPU logical cores (I/O-bound, so threads >> cores is fine)
        base = self.cpu_threads * 2

        # RAM constraint: ~15 MB per thread, use at most 60% of available RAM
        ram_available = self.available_ram_mb
        ram_budget = int(ram_available * 0.6)
        ram_threads = max(2, ram_budget // 15)

        # CPU load constraint: if CPU is already busy, scale down
        if self.cpu_usage_pct > 80:
            cpu_factor = 0.3
        elif self.cpu_usage_pct > 50:
            cpu_factor = 0.6
        else:
            cpu_factor = 1.0

        # Calculate recommended
        recommended = int(min(base, ram_threads) * cpu_factor)
        recommended = max(2, min(recommended, 200))  # clamp 2-200

        # Max safe (absolute ceiling before risk of instability)
        max_safe = min(ram_threads, self.cpu_threads * 8, 500)
        max_safe = max(recommended, max_safe)

        # Build reason
        reasons = []
        if ram_threads < base:
            reasons.append(f"RAM-limited ({ram_available} MB available)")
        if cpu_factor < 1.0:
            reasons.append(f"CPU busy ({self.cpu_usage_pct:.0f}% usage)")
        if not reasons:
            reasons.append("balanced for your specs")

        return recommended, max_safe, ", ".join(reasons)

    def print_report(self):
        """Print a formatted system specs report."""
        rec, max_safe, reason = self.recommend_threads()

        print(f"\n  {C.BOLD}System Profile{C.RST}")
        print(f"  ├─ OS:             {self.os_name} {self.os_version[:30]}")
        print(f"  ├─ Python:         {self.python_version}")
        print(f"  ├─ CPU cores:      {self.cpu_cores} physical / {self.cpu_threads} logical")
        if self.cpu_usage_pct > 0:
            cpu_color = C.GREEN if self.cpu_usage_pct < 50 else C.YELLOW if self.cpu_usage_pct < 80 else C.RED
            print(f"  ├─ CPU usage:      {cpu_color}{self.cpu_usage_pct:.0f}%{C.RST}")
        print(f"  ├─ RAM total:      {self.total_ram_mb:,} MB")
        avail_color = C.GREEN if self.available_ram_mb > 2048 else C.YELLOW if self.available_ram_mb > 512 else C.RED
        print(f"  ├─ RAM available:  {avail_color}{self.available_ram_mb:,} MB{C.RST}")
        if not HAS_PSUTIL:
            print(f"  ├─ {C.DIM}(install psutil for better detection){C.RST}")
        print(f"  ├─ Recommended:    {C.GREEN}{C.BOLD}{rec} threads{C.RST} ({reason})")
        print(f"  └─ Max safe:       {C.YELLOW}{max_safe} threads{C.RST}")

        return rec, max_safe


# ─── Domain Classifier ──────────────────────────────────────────────────────────

class DomainClassifier:
    """
    Classifies domains into categories based on keyword matching
    against the domain name and page title.
    """

    CATEGORIES = {
        "Pornography / Adult": {
            "domains": ["porn", "xxx", "sex", "adult", "nsfw", "hentai", "xvideo",
                        "xhamster", "redtube", "youporn", "brazzers", "onlyfans",
                        "chaturbate", "livejasmin", "cam4", "stripchat", "xnxx",
                        "spankbang", "eporner", "tube8", "pornhub", "fapello",
                        "rule34", "e621", "nhentai", "hanime", "livehdcams"],
            "titles": ["porn", "xxx", "adult", "nsfw", "hentai"],
        },
        "Social Media": {
            "domains": ["facebook", "twitter", "instagram", "tiktok", "snapchat",
                        "linkedin", "reddit", "tumblr", "pinterest", "mastodon",
                        "threads.net", "bsky", "bluesky", "discord", "telegram",
                        "whatsapp", "wechat", "weibo", "vk.com", "ok.ru"],
            "titles": ["social", "feed", "timeline", "connect with"],
        },
        "Gaming": {
            "domains": ["steam", "epicgames", "gog.com", "itch.io", "roblox",
                        "minecraft", "twitch", "xbox", "playstation", "nintendo",
                        "ea.com", "ubisoft", "riot", "blizzard", "activision",
                        "igdb", "rawg", "gamespot", "ign.com", "kotaku",
                        "pcgamer", "gamefaqs", "nexusmods", "moddb", "curseforge"],
            "titles": ["gaming", "video game", "esport", "gameplay", "gamer"],
        },
        "Game Store / Marketplace": {
            "domains": ["store.steampowered", "store.epicgames", "store.playstation",
                        "marketplace.xbox", "humblebundle", "greenmangaming",
                        "kinguin", "g2a.com", "cdkeys", "fanatical"],
            "titles": ["game store", "buy game", "game deal"],
        },
        "Technology": {
            "domains": ["github", "gitlab", "stackoverflow", "hackernews",
                        "techcrunch", "theverge", "arstechnica", "wired.com",
                        "engadget", "tomshardware", "anandtech", "slashdot",
                        "dev.to", "medium.com", "hashnode", "replit", "codepen",
                        "npmjs", "pypi", "crates.io", "docker", "kubernetes",
                        "aws.amazon", "azure.microsoft", "cloud.google",
                        "digitalocean", "heroku", "vercel", "netlify", "render"],
            "titles": ["developer", "programming", "software", "open source",
                       "code", "api", "framework", "devops"],
        },
        "News / Media": {
            "domains": ["cnn.com", "bbc.com", "bbc.co.uk", "nytimes", "reuters",
                        "apnews", "theguardian", "washingtonpost", "foxnews",
                        "nbcnews", "abcnews", "aljazeera", "bloomberg",
                        "cnbc.com", "forbes.com", "businessinsider", "vice.com",
                        "huffpost", "buzzfeed", "dailymail", "news.yahoo"],
            "titles": ["news", "breaking", "headline", "journalist"],
        },
        "Forums / Community": {
            "domains": ["forum", "community", "discuss", "discourse", "phpbb",
                        "vbulletin", "xenforo", "stackexchange", "quora",
                        "answers.yahoo", "4chan", "8chan", "kiwifarms",
                        "somethingawful", "resetera", "neogaf", "voat"],
            "titles": ["forum", "community", "discussion", "board", "thread"],
        },
        "Shopping / E-Commerce": {
            "domains": ["amazon", "ebay", "aliexpress", "alibaba", "walmart",
                        "etsy", "shopify", "target", "bestbuy", "newegg",
                        "wish.com", "temu", "shein", "asos", "zalando",
                        "rakuten", "mercadolibre", "flipkart", "lazada"],
            "titles": ["shop", "buy", "store", "cart", "checkout", "deals"],
        },
        "Streaming / Entertainment": {
            "domains": ["youtube", "youtu.be", "netflix", "hulu", "disneyplus",
                        "hbomax", "primevideo", "peacock", "crunchyroll",
                        "funimation", "spotify", "soundcloud", "deezer",
                        "tidal", "bandcamp", "vimeo", "dailymotion",
                        "twitch", "kick.com", "rumble", "bitchute"],
            "titles": ["stream", "watch", "listen", "movie", "music", "video"],
        },
        "Education": {
            "domains": [".edu", "coursera", "udemy", "edx.org", "khanacademy",
                        "skillshare", "academia.edu", "researchgate",
                        "scholar.google", "jstor", "arxiv", "wikipedia",
                        "wikimedia", "britannica", "w3schools", "freecodecamp"],
            "titles": ["learn", "course", "education", "university", "tutorial",
                       "academy", "school"],
        },
        "Government": {
            "domains": [".gov", ".mil", "government", "whitehouse",
                        "congress.gov", "senate.gov", "europa.eu"],
            "titles": ["government", "federal", "official"],
        },
        "Finance / Crypto": {
            "domains": ["paypal", "stripe", "coinbase", "binance", "kraken",
                        "blockchain", "crypto", "bitcoin", "ethereum",
                        "robinhood", "etrade", "fidelity", "schwab",
                        "bankofamerica", "chase", "wellsfargo", "revolut",
                        "wise.com", "venmo"],
            "titles": ["bank", "finance", "crypto", "trading", "invest",
                       "wallet", "exchange"],
        },
        "AI / Machine Learning": {
            "domains": ["openai", "anthropic", "huggingface", "midjourney",
                        "stability.ai", "replicate", "ollama", "perplexity",
                        "chatgpt", "claude", "gemini", "copilot",
                        "theresanaiforthat", "aitools"],
            "titles": [" ai ", "artificial intelligence", "machine learning",
                       "neural", "llm", "chatbot", "generative"],
        },
        "Search Engine": {
            "domains": ["google.com", "bing.com", "duckduckgo", "yahoo.com",
                        "yandex", "baidu", "brave.com/search", "startpage",
                        "searx", "ecosia"],
            "titles": ["search engine"],
        },
        "Advertising / Tracking": {
            "domains": ["doubleclick", "googlesyndication", "googleadservices",
                        "adnxs", "criteo", "taboola", "outbrain", "trafficjunky",
                        "adtng", "exoclick", "juicyads", "clickadilla",
                        "analytics", "hotjar", "mouseflow", "newrelic"],
            "titles": ["advertising", "ad network", "analytics"],
        },
    }

    def __init__(self):
        # Pre-compile for faster matching
        self._compiled = {}
        for category, rules in self.CATEGORIES.items():
            self._compiled[category] = {
                "domains": [kw.lower() for kw in rules["domains"]],
                "titles": [re.compile(re.escape(kw), re.IGNORECASE) for kw in rules["titles"]],
            }

    def classify(self, domain, title=""):
        """
        Classify a domain into a category.
        Returns the category name or 'Uncategorized'.
        """
        domain_lower = domain.lower()

        # Check domain keywords first (more reliable)
        for category, rules in self._compiled.items():
            for kw in rules["domains"]:
                if kw in domain_lower:
                    return category

        # Fall back to title keywords
        title_lower = (title or "").lower()
        if title_lower:
            for category, rules in self._compiled.items():
                for pattern in rules["titles"]:
                    if pattern.search(title_lower):
                        return category

        return "Uncategorized"


# ─── Aggregator ─────────────────────────────────────────────────────────────────

class Aggregator:
    """
    Collects and organizes all crawled data in real-time.
    Memory-efficient: uses counters instead of storing every page object.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Domain-level tracking
        self.domains = collections.Counter()
        self.domain_first_seen = {}

        # Status code distribution
        self.status_codes = collections.Counter()

        # Content types
        self.content_types = collections.Counter()

        # Counters (not storing full page dicts to save RAM)
        self.total_links_found = 0
        self.total_size_bytes = 0

        # Error tracking
        self.errors = collections.Counter()
        self.error_urls = collections.deque(maxlen=200)  # bounded

        # Onion vs clearnet
        self.onion_count = 0
        self.clearnet_count = 0

        # Domain classifier
        self.classifier = DomainClassifier()
        self.domain_categories = collections.defaultdict(list)  # category -> [domains]
        self.domain_to_category = {}  # domain -> category

        # Timing
        self.start_time = time.time()

        # Largest pages (bounded heap)
        self.largest_pages = []

    def record_page(self, url, status_code, content_type, links_found, depth, size_bytes=0, title=""):
        with self._lock:
            parsed = urlparse(url)
            domain = parsed.netloc

            self.domains[domain] += 1
            if domain not in self.domain_first_seen:
                self.domain_first_seen[domain] = datetime.now().isoformat()

            # Classify domain on first encounter
            if domain not in self.domain_to_category:
                cat = self.classifier.classify(domain, title)
                self.domain_to_category[domain] = cat
                self.domain_categories[cat].append(domain)

            self.status_codes[status_code] += 1

            ct = (content_type or "unknown").split(";")[0].strip()
            self.content_types[ct] += 1

            self.total_links_found += links_found
            self.total_size_bytes += size_bytes

            if ".onion" in domain:
                self.onion_count += 1
            else:
                self.clearnet_count += 1

            # Keep only top 10 largest pages
            self.largest_pages.append((url, size_bytes))
            if len(self.largest_pages) > 20:
                self.largest_pages.sort(key=lambda x: x[1], reverse=True)
                self.largest_pages = self.largest_pages[:10]

    def record_error(self, url, error_msg):
        with self._lock:
            error_type = type(error_msg).__name__ if not isinstance(error_msg, str) else error_msg.split(":")[0]
            self.errors[error_type] += 1
            self.error_urls.append((url, str(error_msg)))

    def get_live_stats(self):
        with self._lock:
            elapsed = time.time() - self.start_time
            total = sum(self.status_codes.values())
            rate = total / elapsed if elapsed > 0 else 0
            return {
                "total_pages": total,
                "total_domains": len(self.domains),
                "total_errors": sum(self.errors.values()),
                "onion_pages": self.onion_count,
                "clearnet_pages": self.clearnet_count,
                "pages_per_sec": round(rate, 2),
                "elapsed": str(timedelta(seconds=int(elapsed))),
                "total_size_mb": round(self.total_size_bytes / (1024 * 1024), 1),
            }

    def generate_report(self):
        """Generate a full aggregation report dict."""
        with self._lock:
            elapsed = time.time() - self.start_time
            total = sum(self.status_codes.values())
            return {
                "summary": {
                    "total_pages_crawled": total,
                    "total_unique_domains": len(self.domains),
                    "total_errors": sum(self.errors.values()),
                    "onion_pages": self.onion_count,
                    "clearnet_pages": self.clearnet_count,
                    "crawl_duration": str(timedelta(seconds=int(elapsed))),
                    "pages_per_second": round(total / elapsed, 2) if elapsed > 0 else 0,
                    "total_data_downloaded_mb": round(self.total_size_bytes / (1024 * 1024), 1),
                    "total_links_found": self.total_links_found,
                },
                "top_domains": self.domains.most_common(30),
                "domains_by_category": {cat: doms for cat, doms in sorted(self.domain_categories.items(), key=lambda x: len(x[1]), reverse=True)},
                "status_code_distribution": dict(self.status_codes.most_common()),
                "content_type_distribution": dict(self.content_types.most_common()),
                "error_distribution": dict(self.errors.most_common()),
                "top_error_urls": list(self.error_urls)[-20:],
                "largest_pages": sorted(self.largest_pages, key=lambda x: x[1], reverse=True)[:10],
            }

    def save_report(self, filepath):
        """Save aggregation report to a JSON file."""
        report = self.generate_report()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        return filepath

    def print_summary(self):
        """Print a formatted summary to console."""
        report = self.generate_report()
        s = report["summary"]

        print(f"\n{'='*60}")
        print(f"{C.CYAN}{C.BOLD}  AGGREGATION REPORT{C.RST}")
        print(f"{'='*60}")

        print(f"\n  {C.BOLD}Overview{C.RST}")
        print(f"  ├─ Pages crawled:    {C.GREEN}{s['total_pages_crawled']}{C.RST}")
        print(f"  ├─ Unique domains:   {C.BLUE}{s['total_unique_domains']}{C.RST}")
        print(f"  ├─ Clearnet pages:   {C.WHITE}{s['clearnet_pages']}{C.RST}")
        print(f"  ├─ Onion pages:      {C.MAGENTA}{s['onion_pages']}{C.RST}")
        print(f"  ├─ Errors:           {C.RED}{s['total_errors']}{C.RST}")
        print(f"  ├─ Data downloaded:  {s['total_data_downloaded_mb']} MB")
        print(f"  ├─ Links found:      {s['total_links_found']}")
        print(f"  ├─ Duration:         {s['crawl_duration']}")
        print(f"  └─ Speed:            {s['pages_per_second']} pages/sec")

        # Status codes
        if report["status_code_distribution"]:
            print(f"\n  {C.BOLD}Status Codes{C.RST}")
            for code, count in sorted(report["status_code_distribution"].items()):
                color = C.GREEN if 200 <= code < 300 else C.YELLOW if 300 <= code < 400 else C.RED
                print(f"    {color}{code}{C.RST}: {count}")

        # Top domains
        if report["top_domains"]:
            print(f"\n  {C.BOLD}Top Domains (by pages){C.RST}")
            for i, (domain, count) in enumerate(report["top_domains"][:15], 1):
                marker = f"{C.MAGENTA}[TOR]{C.RST} " if ".onion" in domain else ""
                print(f"    {C.DIM}{i:>3}.{C.RST} {marker}{domain} — {C.CYAN}{count}{C.RST} pages")

        # Domains by Category
        if report["domains_by_category"]:
            print(f"\n  {C.BOLD}Domains by Category{C.RST}")
            cat_colors = {
                "Pornography / Adult": C.RED,
                "Social Media": C.BLUE,
                "Gaming": C.GREEN,
                "Game Store / Marketplace": C.GREEN,
                "Technology": C.CYAN,
                "News / Media": C.YELLOW,
                "Forums / Community": C.MAGENTA,
                "Shopping / E-Commerce": C.YELLOW,
                "Streaming / Entertainment": C.MAGENTA,
                "Education": C.CYAN,
                "Government": C.WHITE,
                "Finance / Crypto": C.GREEN,
                "AI / Machine Learning": C.CYAN,
                "Search Engine": C.BLUE,
                "Advertising / Tracking": C.GRAY,
                "Uncategorized": C.DIM,
            }
            for cat, domains in report["domains_by_category"].items():
                color = cat_colors.get(cat, C.DIM)
                print(f"\n    {color}{C.BOLD}{cat}{C.RST} ({len(domains)} domains)")
                for d in domains[:8]:
                    print(f"      {C.DIM}•{C.RST} {d}")
                if len(domains) > 8:
                    print(f"      {C.DIM}  ... and {len(domains) - 8} more{C.RST}")

        # Content types
        if report["content_type_distribution"]:
            print(f"\n  {C.BOLD}Content Types{C.RST}")
            for ct, count in list(report["content_type_distribution"].items())[:10]:
                print(f"    {C.DIM}•{C.RST} {ct}: {count}")

        # Errors
        if report["error_distribution"]:
            print(f"\n  {C.BOLD}Error Types{C.RST}")
            for err, count in list(report["error_distribution"].items())[:10]:
                print(f"    {C.RED}•{C.RST} {err}: {count}")

        # Largest pages
        if report["largest_pages"]:
            print(f"\n  {C.BOLD}Largest Pages{C.RST}")
            for url, size in report["largest_pages"][:5]:
                size_kb = size / 1024 if size else 0
                print(f"    {C.DIM}•{C.RST} {size_kb:.1f} KB — {url[:80]}")

        print(f"\n{'='*60}\n")


# ─── Crawler Engine ─────────────────────────────────────────────────────────────

class XueCrawler:
    """
    High-performance continuous BFS web crawler with Tor support.
    Uses ThreadPoolExecutor with optimized connection pooling.
    """

    SKIP_EXTENSIONS = frozenset({
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico",
        ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mkv",
        ".zip", ".rar", ".tar", ".gz", ".7z", ".bz2",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".exe", ".msi", ".dmg", ".deb", ".rpm", ".iso",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".css", ".map",
    })

    # Only parse <a> tags for speed
    LINK_STRAINER = SoupStrainer("a", href=True)

    # Rotating User-Agent pool — real browser strings to avoid detection
    USER_AGENTS = [
        # Chrome on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        # Chrome on Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        # Firefox on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
        # Firefox on Linux
        "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
        # Edge on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
        # Safari on Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        # Chrome on Linux
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    ]

    def __init__(self, seed_url, threads=5, delay=0.5, timeout=10,
                 tor_proxy="socks5h://127.0.0.1:9050", output_file=None,
                 max_depth=0, verbose=False, report_file=None,
                 domains_only=False, auto_threads=False):
        self.seed_url = seed_url
        self.threads = threads
        self.delay = delay
        self.timeout = timeout
        self.tor_proxy = tor_proxy
        self.output_file = output_file
        self.max_depth = max_depth
        self.verbose = verbose
        self.report_file = report_file
        self.domains_only = domains_only
        self.auto_threads = auto_threads

        # Queue: (url, depth)
        self.queue = collections.deque()
        self.queue_lock = threading.Lock()

        # Visited — using a set with a lock for thread safety
        self.visited = set()
        self.visited_lock = threading.Lock()

        # Discovered domains (for --domains-only mode)
        self.discovered_domains = set()
        self.discovered_domains_lock = threading.Lock()

        # Stop flag
        self.stop_event = threading.Event()

        # Stats
        self.total_discovered = 0
        self.stats_lock = threading.Lock()

        # Aggregator
        self.aggregator = Aggregator()

        # Sessions — with optimized connection pooling
        self.clearnet_session = self._build_session(proxy=None)
        self.tor_session = self._build_session(proxy=self.tor_proxy)

        # Output file handle
        self._out_fh = None
        self._out_lock = threading.Lock()
        if self.output_file:
            self._out_fh = open(self.output_file, "a", encoding="utf-8", buffering=8192)

        # Print lock for clean console output
        self._print_lock = threading.Lock()

    def _build_session(self, proxy=None):
        """Build an optimized requests session with large connection pool."""
        s = requests.Session()
        # Base headers — UA is overridden per-request via _random_headers()
        s.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })

        # Mount adapters with large connection pools sized to thread count
        pool_size = max(self.threads, 20)
        adapter = HTTPAdapter(
            pool_connections=pool_size,
            pool_maxsize=pool_size,
            max_retries=1,
            pool_block=False,
        )
        s.mount("http://", adapter)
        s.mount("https://", adapter)

        if proxy:
            s.proxies = {"http": proxy, "https": proxy}
        return s

    def _random_headers(self, url):
        """Generate randomized browser-like headers per request to avoid fingerprinting."""
        ua = random.choice(self.USER_AGENTS)
        parsed = urlparse(url)
        referer = f"{parsed.scheme}://{parsed.netloc}/"

        headers = {
            "User-Agent": ua,
            "Referer": referer,
        }

        # Add Sec-CH-UA for Chrome-like UAs
        if "Chrome" in ua and "Firefox" not in ua:
            # Extract major version
            try:
                ver = ua.split("Chrome/")[1].split(".")[0]
            except (IndexError, ValueError):
                ver = "131"
            if "Edg" in ua:
                headers["Sec-CH-UA"] = f'"Microsoft Edge";v="{ver}", "Chromium";v="{ver}", "Not_A Brand";v="24"'
            else:
                headers["Sec-CH-UA"] = f'"Google Chrome";v="{ver}", "Chromium";v="{ver}", "Not_A Brand";v="24"'
            headers["Sec-CH-UA-Mobile"] = "?0"
            headers["Sec-CH-UA-Platform"] = '"Windows"' if "Windows" in ua else '"macOS"' if "Mac" in ua else '"Linux"'

        return headers

    def _is_onion(self, url):
        return ".onion" in urlparse(url).netloc

    def _get_session(self, url):
        return self.tor_session if self._is_onion(url) else self.clearnet_session

    def _should_skip(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return True
        if not parsed.netloc:
            return True
        ext = os.path.splitext(parsed.path.lower())[1]
        if ext in self.SKIP_EXTENSIONS:
            return True
        return False

    def _normalize_url(self, url):
        """Normalize a URL: remove fragment, strip trailing slash."""
        url, _ = urldefrag(url)
        if url.endswith("/") and url.count("/") > 3:
            url = url.rstrip("/")
        return url

    def _extract_links(self, html, base_url):
        """Extract and resolve links using SoupStrainer for speed."""
        links = set()
        try:
            # SoupStrainer only parses <a> tags — much faster than full parse
            soup = BeautifulSoup(html, "html.parser", parse_only=self.LINK_STRAINER)
            for tag in soup:
                href = tag.get("href", "").strip()
                if not href or href[0] in ("#",) or href.startswith(("javascript:", "mailto:", "tel:", "data:")):
                    continue
                full_url = urljoin(base_url, href)
                full_url = self._normalize_url(full_url)
                if not self._should_skip(full_url):
                    links.add(full_url)
        except Exception:
            pass
        return links

    def _log_url(self, url, status_code, links_count, depth, is_onion):
        """Print and optionally write to file."""
        if is_onion:
            tag = f"{C.MAGENTA}[TOR]{C.RST}"
        else:
            tag = f"{C.BLUE}[WEB]{C.RST}"

        if 200 <= status_code < 300:
            sc = f"{C.GREEN}{status_code}{C.RST}"
        elif 300 <= status_code < 400:
            sc = f"{C.YELLOW}{status_code}{C.RST}"
        else:
            sc = f"{C.RED}{status_code}{C.RST}"

        truncated = url if len(url) <= 100 else url[:97] + "..."
        stats = self.aggregator.get_live_stats()

        with self._print_lock:
            print(
                f"  {tag} {sc} {C.DIM}d={depth}{C.RST} "
                f"{C.DIM}[{links_count} links]{C.RST} "
                f"{truncated} "
                f"{C.GRAY}| {stats['total_pages']} crawled / {stats['total_domains']} domains "
                f"/ {stats['pages_per_sec']}/s / {stats['elapsed']}{C.RST}"
            )

        if self._out_fh:
            with self._out_lock:
                self._out_fh.write(f"{url}\n")

    def _crawl_url(self, url, depth):
        """Fetch a single URL, extract links, enqueue new ones."""
        if self.stop_event.is_set():
            return

        session = self._get_session(url)
        is_onion = self._is_onion(url)

        try:
            resp = session.get(url, timeout=self.timeout, allow_redirects=True,
                               verify=False, stream=True,
                               headers=self._random_headers(url))
            status_code = resp.status_code
            content_type = resp.headers.get("Content-Type", "")

            # Only download and parse HTML responses
            links = set()
            size_bytes = 0
            if "text/html" in content_type:
                # Read content with a size limit (10 MB max) to prevent memory issues
                content = resp.content[:10 * 1024 * 1024]
                size_bytes = len(content)
                try:
                    text = content.decode(resp.encoding or "utf-8", errors="replace")
                except Exception:
                    text = content.decode("utf-8", errors="replace")
                links = self._extract_links(text, url)
            else:
                # For non-HTML, just read headers and close
                size_bytes = int(resp.headers.get("Content-Length", 0))
                resp.close()

            # Record in aggregator
            self.aggregator.record_page(url, status_code, content_type, len(links), depth, size_bytes)

            self._log_url(url, status_code, len(links), depth, is_onion)

            # Enqueue new links
            new_depth = depth + 1
            if self.max_depth > 0 and new_depth > self.max_depth:
                return

            if self.domains_only:
                # Domains-only mode: only queue root URLs of NEW domains/subdomains
                for link in links:
                    parsed_link = urlparse(link)
                    domain = parsed_link.netloc
                    with self.discovered_domains_lock:
                        if domain not in self.discovered_domains:
                            self.discovered_domains.add(domain)
                            root_url = f"{parsed_link.scheme}://{domain}"
                            with self.visited_lock:
                                if root_url not in self.visited:
                                    self.visited.add(root_url)
                                    with self.queue_lock:
                                        self.queue.append((root_url, new_depth))
                                    with self.stats_lock:
                                        self.total_discovered += 1
                                    if self.verbose:
                                        with self._print_lock:
                                            print(f"  {C.CYAN}[NEW]{C.RST} Domain discovered: {C.BOLD}{domain}{C.RST}")
            else:
                # Normal mode: queue every new link
                new_links = []
                for link in links:
                    with self.visited_lock:
                        if link not in self.visited:
                            self.visited.add(link)
                            new_links.append(link)
                if new_links:
                    with self.queue_lock:
                        for link in new_links:
                            self.queue.append((link, new_depth))
                    with self.stats_lock:
                        self.total_discovered += len(new_links)

        except requests.exceptions.ConnectionError as e:
            if self.verbose:
                with self._print_lock:
                    print(f"  {C.RED}[ERR]{C.RST} Connection error: {url[:80]}")
            self.aggregator.record_error(url, f"ConnectionError: {e}")
        except requests.exceptions.Timeout:
            if self.verbose:
                with self._print_lock:
                    print(f"  {C.RED}[ERR]{C.RST} Timeout: {url[:80]}")
            self.aggregator.record_error(url, "Timeout")
        except requests.exceptions.TooManyRedirects:
            if self.verbose:
                with self._print_lock:
                    print(f"  {C.RED}[ERR]{C.RST} Too many redirects: {url[:80]}")
            self.aggregator.record_error(url, "TooManyRedirects")
        except Exception as e:
            if self.verbose:
                with self._print_lock:
                    print(f"  {C.RED}[ERR]{C.RST} {type(e).__name__}: {url[:80]}")
            self.aggregator.record_error(url, f"{type(e).__name__}: {e}")

    def _worker(self):
        """Thread worker: pulls URLs from queue and crawls them."""
        while not self.stop_event.is_set():
            item = None
            with self.queue_lock:
                if self.queue:
                    item = self.queue.popleft()

            if item is None:
                # Queue empty — back off briefly
                if self.stop_event.wait(0.3):
                    break
                continue

            url, depth = item
            self._crawl_url(url, depth)

            if self.delay > 0:
                if self.stop_event.wait(self.delay):
                    break

    def run(self):
        """Start the crawler."""
        print(BANNER)

        # ─── System profiling ───
        profiler = SystemProfiler()
        rec_threads, max_safe, _ = profiler.recommend_threads()
        profiler.print_report()

        # Auto-thread mode: use recommended count
        if self.auto_threads:
            self.threads = rec_threads
            print(f"\n  {C.GREEN}[*]{C.RST} Auto-threads: using {C.BOLD}{self.threads}{C.RST} threads")
            # Rebuild sessions with correct pool size
            self.clearnet_session = self._build_session(proxy=None)
            self.tor_session = self._build_session(proxy=self.tor_proxy)
        elif self.threads > max_safe:
            print(f"\n  {C.YELLOW}[!]{C.RST} {C.BOLD}WARNING:{C.RST} {self.threads} threads exceeds safe limit ({max_safe})")
            print(f"      This may cause instability. Recommended: {rec_threads}")
            ans = input(f"  Continue with {self.threads} threads? [y/N]: ").strip().lower()
            if ans != "y":
                self.threads = rec_threads
                print(f"  {C.GREEN}[*]{C.RST} Using recommended {self.threads} threads instead")
                self.clearnet_session = self._build_session(proxy=None)
                self.tor_session = self._build_session(proxy=self.tor_proxy)

        # ─── Tor check ───
        if self._is_onion(self.seed_url):
            if socks is None:
                print(f"\n  {C.RED}[!]{C.RST} PySocks is required for Tor support.")
                print(f"      pip install PySocks")
                sys.exit(1)
            print(f"\n  {C.MAGENTA}[*]{C.RST} Tor mode — routing through {self.tor_proxy}")
            self._test_tor()
        else:
            print(f"\n  {C.BLUE}[*]{C.RST} Clearnet mode (Tor available for .onion links)")

        # ─── Config summary ───
        print(f"\n  {C.DIM}[*]{C.RST} Seed:    {self.seed_url}")
        print(f"  {C.DIM}[*]{C.RST} Threads: {C.BOLD}{self.threads}{C.RST}")
        print(f"  {C.DIM}[*]{C.RST} Delay:   {self.delay}s")
        print(f"  {C.DIM}[*]{C.RST} Timeout: {self.timeout}s")
        if self.domains_only:
            print(f"  {C.CYAN}[*]{C.RST} Mode:    {C.BOLD}DOMAINS ONLY{C.RST} (skipping endpoints, crawling domains/subdomains)")
        if self.max_depth:
            print(f"  {C.DIM}[*]{C.RST} Max depth: {self.max_depth}")
        if self.output_file:
            print(f"  {C.DIM}[*]{C.RST} Output:  {self.output_file}")
        if self.report_file:
            print(f"  {C.DIM}[*]{C.RST} Report:  {self.report_file}")
        print(f"\n  {C.YELLOW}Press CTRL+C to stop and view aggregation report{C.RST}\n")

        # Seed the queue
        normalized = self._normalize_url(self.seed_url)
        self.visited.add(normalized)
        self.queue.append((normalized, 0))
        self.total_discovered = 1

        # Pre-populate discovered domains with seed
        seed_domain = urlparse(normalized).netloc
        self.discovered_domains.add(seed_domain)

        # Catch CTRL+C
        def signal_handler(sig, frame):
            print(f"\n\n  {C.YELLOW}[!]{C.RST} CTRL+C received — stopping crawler...\n")
            self.stop_event.set()

        signal.signal(signal.SIGINT, signal_handler)

        # Launch worker threads via ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.threads, thread_name_prefix="xue") as executor:
            futures = [executor.submit(self._worker) for _ in range(self.threads)]

            # Wait for stop signal
            try:
                while not self.stop_event.is_set():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                self.stop_event.set()

            # Wait for all workers to finish (gracefully handle stragglers)
            for f in futures:
                try:
                    f.result(timeout=3)
                except (TimeoutError, Exception):
                    f.cancel()

        # Print aggregation report
        self.aggregator.print_summary()

        # Save report file
        if self.report_file:
            self.aggregator.save_report(self.report_file)
            print(f"  {C.GREEN}[+]{C.RST} Aggregation report saved to {self.report_file}")

        # Save URL list
        if self._out_fh:
            self._out_fh.flush()
            self._out_fh.close()
            print(f"  {C.GREEN}[+]{C.RST} URL list saved to {self.output_file}")

        print(f"  {C.CYAN}[*]{C.RST} Done. Total discovered: {self.total_discovered}")

    def _test_tor(self):
        """Quick verification that Tor connection works."""
        print(f"  {C.DIM}[*]{C.RST} Testing Tor connection...", end=" ", flush=True)
        try:
            resp = self.tor_session.get("http://check.torproject.org/api/ip", timeout=15)
            data = resp.json()
            if data.get("IsTor"):
                print(f"{C.GREEN}OK{C.RST} (IP: {data.get('IP', 'unknown')})")
            else:
                print(f"{C.YELLOW}WARNING{C.RST} — connected but Tor not detected")
        except Exception as e:
            print(f"{C.RED}FAILED{C.RST}")
            print(f"  {C.RED}[!]{C.RST} Could not connect to Tor: {e}")
            print(f"  {C.DIM}    Make sure Tor service is running on {self.tor_proxy}{C.RST}")
            ans = input(f"\n  Continue without Tor? [y/N]: ").strip().lower()
            if ans != "y":
                sys.exit(1)


# ─── CLI ────────────────────────────────────────────────────────────────────────

def main():
    # Suppress InsecureRequestWarning
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    parser = argparse.ArgumentParser(
        prog="xue",
        description="Xue — Continuous Internet Crawler with Tor Support & Aggregator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python xue.py -u https://example.com
  python xue.py -u https://example.com --auto -d 0.2 -o urls.txt -r report.json
  python xue.py -u https://example.com -t 50 -d 0.3
  python xue.py -u http://someonion.onion -v --tor-proxy socks5h://127.0.0.1:9050
        """
    )

    parser.add_argument("-u", "--url", required=True, help="Seed URL to start crawling")
    parser.add_argument("-t", "--threads", type=int, default=10, help="Concurrent threads (default: 10)")
    parser.add_argument("--auto", action="store_true", dest="auto_threads",
                        help="Auto-detect optimal thread count based on system specs")
    parser.add_argument("-d", "--delay", type=float, default=0.5, help="Delay between requests per thread in seconds (default: 0.5)")
    parser.add_argument("-o", "--output", help="File to append discovered URLs to")
    parser.add_argument("-r", "--report", help="Save aggregation report as JSON file")
    parser.add_argument("--tor-proxy", default="socks5h://127.0.0.1:9050", help="Tor SOCKS5 proxy (default: socks5h://127.0.0.1:9050)")
    parser.add_argument("--timeout", type=int, default=10, help="Request timeout in seconds (default: 10)")
    parser.add_argument("--max-depth", type=int, default=0, help="Max crawl depth, 0 = unlimited (default: 0)")
    parser.add_argument("--domains-only", action="store_true", help="Only crawl domains and subdomains, skip endpoints")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose error output")

    args = parser.parse_args()

    # Basic URL validation
    parsed = urlparse(args.url)
    if parsed.scheme not in ("http", "https"):
        print(f"  {C.RED}[!]{C.RST} Invalid URL scheme. Use http:// or https://")
        sys.exit(1)
    if not parsed.netloc:
        print(f"  {C.RED}[!]{C.RST} Invalid URL. Must include a domain.")
        sys.exit(1)

    crawler = XueCrawler(
        seed_url=args.url,
        threads=args.threads,
        delay=args.delay,
        timeout=args.timeout,
        tor_proxy=args.tor_proxy,
        output_file=args.output,
        max_depth=args.max_depth,
        verbose=args.verbose,
        report_file=args.report,
        domains_only=args.domains_only,
        auto_threads=args.auto_threads,
    )
    crawler.run()


if __name__ == "__main__":
    main()
