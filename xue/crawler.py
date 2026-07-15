import collections
import json
import os
import random
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, SoupStrainer
from requests.adapters import HTTPAdapter

try:
    import socks
except ImportError:
    socks = None

from xue.adaptive_delay import AdaptiveDelay
from xue.aggregator import Aggregator
from xue.ansi import BANNER, C
from xue.api_crawl import ApiCrawler
from xue.budget import CrawlBudget
from xue.config import CrawlerConfig
from xue.content_extractor import extract_text
from xue.fingerprint import FingerprintDedup
from xue.graph_export import GraphExporter
from xue.harvester import DataHarvester
from xue.js_renderer import JsRenderer
from xue.plugin import PluginManager
from xue.profiler import SystemProfiler
from xue.proxy_pool import ProxyPool
from xue.redis_queue import RedisQueue
from xue.robots import RobotsManager
from xue.secret_detector import SecretDetector
from xue.seo_analyzer import analyze_seo
from xue.sqlite_store import SqliteStore
from xue.tech_fingerprint import TechFingerprinter
from xue.url_normalizer import normalize_url
from xue.wayback import WaybackLookup


class XueCrawler:
    SKIP_EXTENSIONS = frozenset({
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico",
        ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mkv",
        ".zip", ".rar", ".tar", ".gz", ".7z", ".bz2",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".exe", ".msi", ".dmg", ".deb", ".rpm", ".iso",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".css", ".map",
    })

    LINK_STRAINER = SoupStrainer("a", href=True)

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
        "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    ]

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.queue: collections.deque[tuple[str, int]] = collections.deque()
        self.queue_lock = threading.Lock()
        self.visited: set[str] = set()
        self.visited_lock = threading.Lock()
        self.discovered_domains: set[str] = set()
        self.discovered_domains_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.total_discovered = 0
        self.stats_lock = threading.Lock()
        self.aggregator = Aggregator()
        self.clearnet_session = self._build_session(proxy=None)
        self.tor_session = self._build_session(proxy=self.config.tor_proxy)
        self._out_fh = None
        self._out_lock = threading.Lock()
        if self.config.output_file:
            self._out_fh = open(self.config.output_file, "a", encoding="utf-8", buffering=8192)
        self._print_lock = threading.Lock()
        self._robots_manager = RobotsManager(self.clearnet_session, timeout=self.config.timeout)
        self._domain_last_request: dict[str, float] = {}
        self._domain_rate_lock = threading.Lock()
        self._log_fh = None
        self._log_lock = threading.Lock()
        if self.config.log_file:
            self._log_fh = open(self.config.log_file, "a", encoding="utf-8", buffering=8192)
        self._js_renderer = None
        if self.config.js_render:
            try:
                self._js_renderer = JsRenderer()
                self._js_renderer.start(self.config.threads)
                print(f"  {C.GREEN}[+]{C.RST} Playwright browser cluster: {len(self._js_renderer._contexts)} contexts")
            except Exception as e:
                print(f"  {C.RED}[!]{C.RST} Failed to initialize Playwright: {e}")
                self.config.js_render = False
        self._proxy_pool = ProxyPool(proxy_file=self.config.proxy_file, proxy_api=self.config.proxy_api) if (self.config.proxy_file or self.config.proxy_api) else None
        self._fingerprint_dedup = FingerprintDedup() if self.config.dedup else None
        self._secret_detector = SecretDetector() if self.config.secrets else None
        self._harvester = DataHarvester() if self.config.harvest else None
        self._wayback = WaybackLookup(self.clearnet_session, timeout=self.config.timeout) if self.config.wayback else None
        self._adaptive_delay = AdaptiveDelay(base_delay=self.config.delay) if self.config.adaptive_delay else None
        self._plugin_manager = PluginManager()
        if self.config.plugin_dir:
            self._plugin_manager.load_from_directory(self.config.plugin_dir)
        self._graph_exporter = GraphExporter() if self.config.graph_file else None
        self._api_crawler = ApiCrawler() if self.config.api_mode else None
        self._crawl_budget = CrawlBudget(
            max_pages_per_domain=self.config.max_pages_per_domain,
            max_time_per_domain=self.config.max_time_per_domain,
            max_size_per_domain=self.config.max_size_per_domain,
        ) if (self.config.max_pages_per_domain or self.config.max_time_per_domain or self.config.max_size_per_domain) else None
        self._tech_fingerprinter = TechFingerprinter() if self.config.tech_fingerprint else None
        try:
            from xue.redis_queue import HAS_REDIS
            self._redis_queue = RedisQueue(self.config.redis_url) if self.config.redis_url and HAS_REDIS else None
        except ImportError:
            self._redis_queue = None

    def _build_session(self, proxy=None):
        s = requests.Session()
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
        pool_size = max(self.config.threads, 20)
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
        ua = random.choice(self.USER_AGENTS)
        parsed = urlparse(url)
        referer = f"{parsed.scheme}://{parsed.netloc}/"
        headers = {"User-Agent": ua, "Referer": referer}
        if "Chrome" in ua and "Firefox" not in ua:
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
        if self.config.normalize_urls:
            return normalize_url(
                url,
                strip_www=self.config.strip_www,
                sort_query=self.config.sort_query_params,
            )
        url, _ = urldefrag(url)
        if url.endswith("/") and url.count("/") > 3:
            url = url.rstrip("/")
        return url

    def _matches_scope(self, url):
        if not self.config.scope:
            return True
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        scope = self.config.scope.lower()
        return host == scope or host.endswith(f".{scope}")

    def _matches_exclude(self, url):
        for pattern in self.config.exclude_compiled:
            if pattern.search(url):
                return True
        return False

    def _matches_content_type(self, content_type):
        if not self.config.allowed_content_type_list:
            return True
        ct = (content_type or "").split(";")[0].strip().lower()
        return any(a.lower() in ct for a in self.config.allowed_content_type_list)

    def _wait_per_domain(self, url):
        domain = urlparse(url).netloc
        with self._domain_rate_lock:
            last = self._domain_last_request.get(domain, 0)
            now = time.time()
            effective_delay = self._adaptive_delay.get_delay() if self.config.adaptive_delay else self.config.delay
            wait = effective_delay - (now - last)
            if wait > 0:
                time.sleep(wait)
            self._domain_last_request[domain] = time.time()

    def _extract_links_and_title(self, html, base_url):
        links = set()
        title = ""
        try:
            soup = BeautifulSoup(html, "html.parser")
            title_tag = soup.find("title")
            if title_tag and title_tag.get_text(strip=True):
                title = title_tag.get_text(strip=True)
            for tag in soup.find_all("a", href=True):
                href = tag.get("href", "").strip()
                if not href or href[0] in ("#",) or href.startswith(("javascript:", "mailto:", "tel:", "data:")):
                    continue
                full_url = urljoin(base_url, href)
                full_url = self._normalize_url(full_url)
                if not self._should_skip(full_url):
                    links.add(full_url)
        except Exception:
            pass
        return links, title

    def _log_url(self, url, status_code, links_count, depth, is_onion):
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
                if self.config.output_format == "csv":
                    self._out_fh.write(f'"{url.replace(chr(34), chr(34)+chr(34))}"\n')
                elif self.config.output_format == "jsonl":
                    self._out_fh.write(json.dumps({"url": url}) + "\n")
                else:
                    self._out_fh.write(f"{url}\n")
        if self._log_fh:
            with self._log_lock:
                log_entry = json.dumps({
                    "timestamp": datetime.utcnow().isoformat(),
                    "url": url,
                    "status": status_code,
                    "links_found": links_count,
                    "depth": depth,
                })
                self._log_fh.write(log_entry + "\n")

    def _save_checkpoint(self):
        from xue.checkpoint import Checkpoint
        with self.visited_lock:
            visited_list = list(self.visited)
        with self.queue_lock:
            queue_list = list(self.queue)
        with self.discovered_domains_lock:
            domains_list = list(self.discovered_domains)
        with self.stats_lock:
            total = self.total_discovered
        cp = Checkpoint(
            seed_url=self.config.seed_url,
            visited=visited_list,
            queue=[(u, d) for u, d in queue_list],
            discovered_domains=domains_list,
            total_discovered=total,
            timestamp=datetime.utcnow().isoformat(),
        )
        try:
            cp.save("xue_checkpoint.json")
        except Exception as e:
            print(f"\n  {C.RED}[!]{C.RST} Failed to save checkpoint: {e}")

    def _crawl_url(self, url, depth):
        if self.stop_event.is_set():
            return

        self._plugin_manager.emit("on_link", url=url, depth=depth)

        if not self._matches_scope(url):
            return
        if self._matches_exclude(url):
            return

        if self._redis_queue and self._redis_queue.is_visited(url):
            return

        if self.config.respect_robots:
            if not self._robots_manager.is_allowed(url):
                if self.config.verbose:
                    with self._print_lock:
                        print(f"  {C.YELLOW}[ROBOT]{C.RST} Blocked by robots.txt: {url[:80]}")
                self.aggregator.record_robots_blocked()
                return

        self._wait_per_domain(url)

        session = self._get_session(url)
        is_onion = self._is_onion(url)

        proxy = None
        if self._proxy_pool:
            proxy = self._proxy_pool.get_proxy()

        try:
            html = None
            status_code = 0
            content_type = ""
            response_headers: dict[str, str] = {}
            links: set[str] = set()
            size_bytes = 0
            title = ""

            if self.config.js_render and self._js_renderer:
                html, status_code, content_type = self._js_renderer.render(url, self.config.timeout)

            if html is None:
                req_session = session
                if proxy:
                    req_session = self._build_session(proxy=proxy)

                resp = req_session.get(url, timeout=self.config.timeout, allow_redirects=True,
                                       verify=False, stream=True,
                                       headers=self._random_headers(url))
                status_code = resp.status_code
                content_type = resp.headers.get("Content-Type", "")
                response_headers = dict(resp.headers)

                if self._proxy_pool and status_code >= 400:
                    self._proxy_pool.mark_bad(proxy)

                if not self._matches_content_type(content_type):
                    resp.close()
                    return

                if status_code in (429, 503):
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        wait_secs = int(retry_after) if retry_after.isdigit() else 5
                        if self.config.verbose:
                            with self._print_lock:
                                print(f"  {C.YELLOW}[WAIT]{C.RST} Retry-After: {wait_secs}s for {url[:80]}")
                        self.aggregator.record_retry_after()
                        time.sleep(wait_secs)
                        with self.queue_lock:
                            self.queue.append((url, depth))
                        return

                if "text/html" in content_type:
                    content = resp.content[:10 * 1024 * 1024]
                    size_bytes = len(content)
                    try:
                        text = content.decode(resp.encoding or "utf-8", errors="replace")
                    except Exception:
                        text = content.decode("utf-8", errors="replace")
                    links, title = self._extract_links_and_title(text, url)
                    html = text
                else:
                    size_bytes = int(resp.headers.get("Content-Length", 0))
                    resp.close()

            if html is not None and self.config.domains_only and "text/html" in content_type:
                links, title = self._extract_links_and_title(html, url)
                size_bytes = len(html)

            if self.config.adaptive_delay and self._adaptive_delay:
                self._adaptive_delay.record_result(status_code)

            if self.config.dedup and html and self._fingerprint_dedup:
                if self._fingerprint_dedup.is_duplicate(url, html):
                    self.aggregator.record_duplicate()
                    if self.config.verbose:
                        with self._print_lock:
                            print(f"  {C.DIM}[DUP]{C.RST} Duplicate: {url[:80]}")
                    return

            if self.config.secrets and html and self._secret_detector:
                findings = self._secret_detector.scan(url, html)
                if findings and self.config.verbose:
                    with self._print_lock:
                        for f in findings:
                            print(f"  {C.RED}[SECRET]{C.RST} {f['type']}: {f['value']} in {f['url'][:60]}")

            if self.config.harvest and html and self._harvester:
                harvested = self._harvester.harvest(html)
                if harvested["emails"] and self.config.verbose:
                    with self._print_lock:
                        for email in harvested["emails"]:
                            print(f"  {C.GREEN}[EMAIL]{C.RST} {email}")

            if self.config.api_mode and self._api_crawler and html:
                if self._api_crawler.is_api_response(content_type, html):
                    has_pagination = self._api_crawler.detect_pagination(html)
                    self._api_crawler.record_endpoint(url, has_pagination)
                    if self.config.verbose:
                        with self._print_lock:
                            pag = " (paginated)" if has_pagination else ""
                            print(f"  {C.CYAN}[API]{C.RST} {url[:80]}{pag}")

            if self.config.tech_fingerprint and html and self._tech_fingerprinter:
                findings = self._tech_fingerprinter.scan(html, response_headers)
                if findings:
                    self.aggregator.record_tech_findings(url, findings)
                    if self.config.verbose:
                        with self._print_lock:
                            tech_names = ", ".join(f"{f.name}({f.confidence})" for f in findings)
                            print(f"  {C.CYAN}[TECH]{C.RST} {tech_names} — {url[:60]}")

            if self.config.extract_content and html:
                extracted = extract_text(html)
                if extracted.text:
                    self.aggregator.record_content(url, extracted)
                    if self.config.verbose:
                        with self._print_lock:
                            print(f"  {C.DIM}[CONTENT]{C.RST} {extracted.word_count} words — {url[:60]}")

            if self.config.seo_analysis and html:
                seo = analyze_seo(html, url)
                self.aggregator.record_seo(seo)
                if seo.heading_issues and self.config.verbose:
                    with self._print_lock:
                        for issue in seo.heading_issues:
                            print(f"  {C.YELLOW}[SEO]{C.RST} {issue} — {url[:60]}")

            if self.config.wayback and status_code == 404 and self._wayback:
                archived = self._wayback.lookup(url)
                if archived and self.config.verbose:
                    with self._print_lock:
                        print(f"  {C.BLUE}[WAYBACK]{C.RST} Archived: {archived}")

            if self._crawl_budget:
                self._crawl_budget.record_page(url, size_bytes)
            self.aggregator.record_page(url, status_code, content_type, len(links), depth, size_bytes, title)
            self._log_url(url, status_code, len(links), depth, is_onion)

            self._plugin_manager.emit("on_page", url=url, status=status_code, links=len(links), depth=depth)

            if self._graph_exporter:
                for link in links:
                    self._graph_exporter.add_edge(url, link)

            new_depth = depth + 1
            if self.config.max_depth > 0 and new_depth > self.config.max_depth:
                return

            if self.config.domains_only:
                for link in links:
                    if self._crawl_budget and not self._crawl_budget.check_url(link):
                        self.aggregator.record_budget_exceeded(link)
                        continue
                    parsed_link = urlparse(link)
                    domain = parsed_link.netloc
                    with self.discovered_domains_lock:
                        if domain not in self.discovered_domains:
                            self.discovered_domains.add(domain)
                            self._plugin_manager.emit("on_domain_discovered", domain=domain)
                            root_url = f"{parsed_link.scheme}://{domain}"
                            with self.visited_lock:
                                if root_url not in self.visited:
                                    self.visited.add(root_url)
                                    with self.queue_lock:
                                        self.queue.append((root_url, new_depth))
                                    if self._redis_queue:
                                        self._redis_queue.mark_visited(root_url)
                                        self._redis_queue.enqueue(root_url, new_depth)
                                    with self.stats_lock:
                                        self.total_discovered += 1
                                    if self.config.verbose:
                                        with self._print_lock:
                                            print(f"  {C.CYAN}[NEW]{C.RST} Domain discovered: {C.BOLD}{domain}{C.RST}")
            else:
                new_links = []
                for link in links:
                    if self._crawl_budget and not self._crawl_budget.check_url(link):
                        self.aggregator.record_budget_exceeded(link)
                        continue
                    with self.visited_lock:
                        if link not in self.visited:
                            self.visited.add(link)
                            new_links.append(link)
                if new_links:
                    with self.queue_lock:
                        for link in new_links:
                            self.queue.append((link, new_depth))
                    if self._redis_queue:
                        for link in new_links:
                            self._redis_queue.mark_visited(link)
                            self._redis_queue.enqueue(link, new_depth)
                    with self.stats_lock:
                        self.total_discovered += len(new_links)

        except requests.exceptions.ConnectionError as e:
            if self._proxy_pool and proxy:
                self._proxy_pool.mark_bad(proxy)
            if self.config.verbose:
                with self._print_lock:
                    print(f"  {C.RED}[ERR]{C.RST} Connection error: {url[:80]}")
            self.aggregator.record_error(url, f"ConnectionError: {e}")
            self._plugin_manager.emit("on_error", url=url, error=str(e))
        except requests.exceptions.Timeout:
            if self._proxy_pool and proxy:
                self._proxy_pool.mark_bad(proxy)
            if self.config.verbose:
                with self._print_lock:
                    print(f"  {C.RED}[ERR]{C.RST} Timeout: {url[:80]}")
            self.aggregator.record_error(url, "Timeout")
            self._plugin_manager.emit("on_error", url=url, error="Timeout")
        except requests.exceptions.TooManyRedirects:
            if self.config.verbose:
                with self._print_lock:
                    print(f"  {C.RED}[ERR]{C.RST} Too many redirects: {url[:80]}")
            self.aggregator.record_error(url, "TooManyRedirects")
            self._plugin_manager.emit("on_error", url=url, error="TooManyRedirects")
        except Exception as e:
            if self.config.verbose:
                with self._print_lock:
                    print(f"  {C.RED}[ERR]{C.RST} {type(e).__name__}: {url[:80]}")
            self.aggregator.record_error(url, f"{type(e).__name__}: {e}")
            self._plugin_manager.emit("on_error", url=url, error=str(e))

    def _worker(self):
        while not self.stop_event.is_set():
            item = None
            if self._redis_queue:
                result = self._redis_queue.dequeue()
                if result:
                    item = result
            if item is None:
                with self.queue_lock:
                    if self.queue:
                        strat = self.config.crawl_strategy
                        if strat == "dfs":
                            item = self.queue.pop()
                        elif strat == "priority":
                            budget = self._crawl_budget
                            best = min(self.queue, key=lambda x: budget.status(x[0])["pages"] if budget else 0)
                            self.queue.remove(best)
                            item = best
                        else:
                            item = self.queue.popleft()
            if item is None:
                if self.stop_event.wait(0.3):
                    break
                continue
            url, depth = item
            self._crawl_url(url, depth)

    def run(self):
        print(BANNER)
        profiler = SystemProfiler()
        rec_threads, max_safe, _ = profiler.recommend_threads()
        profiler.print_report()

        if self.config.auto_threads:
            self.config.threads = rec_threads
            print(f"\n  {C.GREEN}[*]{C.RST} Auto-threads: using {C.BOLD}{self.config.threads}{C.RST} threads")
            self.clearnet_session = self._build_session(proxy=None)
            self.tor_session = self._build_session(proxy=self.config.tor_proxy)
        elif self.config.threads > max_safe:
            print(f"\n  {C.YELLOW}[!]{C.RST} {C.BOLD}WARNING:{C.RST} {self.config.threads} threads exceeds safe limit ({max_safe})")
            print(f"      This may cause instability. Recommended: {rec_threads}")
            ans = input(f"  Continue with {self.config.threads} threads? [y/N]: ").strip().lower()
            if ans != "y":
                self.config.threads = rec_threads
                print(f"  {C.GREEN}[*]{C.RST} Using recommended {self.config.threads} threads instead")
                self.clearnet_session = self._build_session(proxy=None)
                self.tor_session = self._build_session(proxy=self.config.tor_proxy)

        if self._is_onion(self.config.seed_url):
            if socks is None:
                print(f"\n  {C.RED}[!]{C.RST} PySocks is required for Tor support.")
                print("      pip install PySocks")
                sys.exit(1)
            print(f"\n  {C.MAGENTA}[*]{C.RST} Tor mode — routing through {self.config.tor_proxy}")
            self._test_tor()
        else:
            print(f"\n  {C.BLUE}[*]{C.RST} Clearnet mode (Tor available for .onion links)")

        print(f"\n  {C.DIM}[*]{C.RST} Seed:    {self.config.seed_url}")
        print(f"  {C.DIM}[*]{C.RST} Threads: {C.BOLD}{self.config.threads}{C.RST}")
        print(f"  {C.DIM}[*]{C.RST} Delay:   {self.config.delay}s")
        print(f"  {C.DIM}[*]{C.RST} Timeout: {self.config.timeout}s")
        if self.config.domains_only:
            print(f"  {C.CYAN}[*]{C.RST} Mode:    {C.BOLD}DOMAINS ONLY{C.RST}")
        if self.config.respect_robots:
            print(f"  {C.GREEN}[*]{C.RST} Robots:  {C.BOLD}Respecting robots.txt{C.RST}")
        if self.config.scope:
            print(f"  {C.CYAN}[*]{C.RST} Scope:   {self.config.scope}")
        if self.config.exclude_patterns:
            print(f"  {C.YELLOW}[*]{C.RST} Exclude: {len(self.config.exclude_patterns)} patterns")
        if self.config.allowed_content_type_list:
            print(f"  {C.DIM}[*]{C.RST} Content types: {', '.join(self.config.allowed_content_type_list)}")
        if self.config.js_render:
            print(f"  {C.MAGENTA}[*]{C.RST} JS Render: {C.BOLD}Enabled{C.RST}")
        if self.config.dedup:
            print(f"  {C.DIM}[*]{C.RST} Dedup:   {C.BOLD}SimHash fingerprinting{C.RST}")
        if self.config.secrets:
            print(f"  {C.RED}[*]{C.RST} Secrets: {C.BOLD}Scanning for leaks{C.RST}")
        if self.config.harvest:
            print(f"  {C.GREEN}[*]{C.RST} Harvest: {C.BOLD}Emails, phones, social{C.RST}")
        if self.config.wayback:
            print(f"  {C.BLUE}[*]{C.RST} Wayback: {C.BOLD}Archive lookup{C.RST}")
        if self.config.adaptive_delay:
            print(f"  {C.YELLOW}[*]{C.RST} Adaptive: {C.BOLD}Delay auto-tuning{C.RST}")
        if self.config.api_mode:
            print(f"  {C.CYAN}[*]{C.RST} API Mode: {C.BOLD}Detecting API endpoints{C.RST}")
        if self._proxy_pool:
            print(f"  {C.GREEN}[*]{C.RST} Proxies: {C.BOLD}{self._proxy_pool.size()} in pool{C.RST}")
        if self._redis_queue:
            print(f"  {C.CYAN}[*]{C.RST} Redis:   {C.BOLD}Distributed queue{C.RST}")
        if self.config.plugin_dir:
            print(f"  {C.MAGENTA}[*]{C.RST} Plugins: {C.BOLD}{self.config.plugin_dir}{C.RST}")
        if self.config.max_depth:
            print(f"  {C.DIM}[*]{C.RST} Max depth: {self.config.max_depth}")
        if self.config.crawl_strategy != "bfs":
            print(f"  {C.CYAN}[*]{C.RST} Strategy: {C.BOLD}{self.config.crawl_strategy}{C.RST}")
        if self._crawl_budget:
            print(f"  {C.GREEN}[*]{C.RST} Budget:   per-domain (pages={self.config.max_pages_per_domain}, "
                  f"time={self.config.max_time_per_domain}s, size={self.config.max_size_per_domain}B)")
        if self.config.tech_fingerprint:
            print(f"  {C.CYAN}[*]{C.RST} Tech FP:  {C.BOLD}Enabled{C.RST}")
        if self.config.extract_content:
            print(f"  {C.DIM}[*]{C.RST} Extract:  {C.BOLD}Content extraction enabled{C.RST}")
        if self.config.seo_analysis:
            print(f"  {C.YELLOW}[*]{C.RST} SEO:      {C.BOLD}Analysis enabled{C.RST}")
        if self.config.resume_checkpoint:
            print(f"  {C.CYAN}[*]{C.RST} Resume:  {self.config.resume_checkpoint}")
        if self.config.db_path:
            print(f"  {C.DIM}[*]{C.RST} DB:      {self.config.db_path}")
        if self.config.graph_file:
            print(f"  {C.DIM}[*]{C.RST} Graph:   {self.config.graph_file} ({self.config.graph_format})")
        if self.config.output_file:
            print(f"  {C.DIM}[*]{C.RST} Output:  {self.config.output_file} ({self.config.output_format})")
        if self.config.report_file:
            print(f"  {C.DIM}[*]{C.RST} Report:  {self.config.report_file}")
        if self.config.log_file:
            print(f"  {C.DIM}[*]{C.RST} Log:     {self.config.log_file}")
        print(f"\n  {C.YELLOW}Press CTRL+C to stop and view aggregation report{C.RST}\n")

        self._plugin_manager.emit("on_start", seed_url=self.config.seed_url)

        resumed = False
        if self.config.resume_checkpoint and os.path.exists(self.config.resume_checkpoint):
            try:
                from xue.checkpoint import Checkpoint
                cp = Checkpoint.load(self.config.resume_checkpoint)
                with self.visited_lock:
                    self.visited.update(cp.visited)
                with self.queue_lock:
                    self.queue.extend(cp.queue)
                with self.discovered_domains_lock:
                    self.discovered_domains.update(cp.discovered_domains)
                with self.stats_lock:
                    self.total_discovered = cp.total_discovered
                print(f"  {C.GREEN}[+]{C.RST} Resumed from checkpoint: {self.config.resume_checkpoint}")
                resumed = True
            except Exception as e:
                print(f"  {C.RED}[!]{C.RST} Failed to load checkpoint: {e}")

        sqlite_store = None
        if self.config.db_path:
            try:
                sqlite_store = SqliteStore(self.config.db_path)
                if not resumed:
                    print(f"  {C.GREEN}[+]{C.RST} SQLite database opened: {self.config.db_path}")
            except Exception as e:
                print(f"  {C.RED}[!]{C.RST} Failed to open SQLite: {e}")

        if not resumed:
            normalized = self._normalize_url(self.config.seed_url)
            self.visited.add(normalized)
            self.queue.append((normalized, 0))
            self.total_discovered = 1
            seed_domain = urlparse(normalized).netloc
            self.discovered_domains.add(seed_domain)
            if sqlite_store:
                sqlite_store.add_domain(seed_domain)
                sqlite_store.queue_url(normalized, 0)
            if self._redis_queue:
                self._redis_queue.mark_visited(normalized)
                self._redis_queue.enqueue(normalized, 0)

        def signal_handler(sig, frame):
            print(f"\n\n  {C.YELLOW}[!]{C.RST} CTRL+C received — stopping crawler...\n")
            self.stop_event.set()
            self._save_checkpoint()
            if sqlite_store:
                sqlite_store.close()

        signal.signal(signal.SIGINT, signal_handler)

        with ThreadPoolExecutor(max_workers=self.config.threads, thread_name_prefix="xue") as executor:
            futures = [executor.submit(self._worker) for _ in range(self.config.threads)]
            try:
                while not self.stop_event.is_set():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                self.stop_event.set()
                self._save_checkpoint()
            for f in futures:
                try:
                    f.result(timeout=3)
                except (TimeoutError, Exception):
                    f.cancel()

        self._plugin_manager.emit("on_stop")

        self.aggregator.print_summary()

        if self._graph_exporter and self.config.graph_file:
            base, ext = os.path.splitext(self.config.graph_file)
            fmt = self.config.graph_format
            if fmt == "json":
                self._graph_exporter.export_json(self.config.graph_file)
            elif fmt == "dot":
                self._graph_exporter.export_dot(self.config.graph_file)
            elif fmt == "gexf":
                self._graph_exporter.export_gexf(self.config.graph_file)
            else:
                self._graph_exporter.export_json(self.config.graph_file)
            print(f"  {C.GREEN}[+]{C.RST} Graph exported to {self.config.graph_file} ({fmt})")

        if self.config.tech_fingerprint and self._tech_fingerprinter:
            tf = self.aggregator.tech_findings
            if tf:
                print(f"\n  {C.BOLD}Technology Fingerprinting{C.RST}")
                for domain, findings in sorted(tf.items())[:15]:
                    techs = ", ".join(f"{f['name']} ({f['confidence']})" for f in findings[:5])
                    print(f"  {C.CYAN}•{C.RST} {domain}: {techs}")

        if self.config.extract_content:
            cs = self.aggregator.content_stats
            if cs["pages_extracted"]:
                print(f"\n  {C.BOLD}Content Extraction{C.RST}")
                print(f"  ├─ Pages extracted: {cs['pages_extracted']}")
                print(f"  ├─ Total words:     {cs['total_words']:,}")
                print(f"  └─ Total chars:     {cs['total_chars']:,}")

        if self.config.seo_analysis:
            seo = self.aggregator.seo_reports
            if seo:
                total_issues = sum(len(r.get("issues", [])) for r in seo)
                no_h1 = sum(1 for r in seo if r.get("h1_count", 1) == 0)
                no_desc = sum(1 for r in seo if not r.get("meta_description", ""))
                no_canonical = sum(1 for r in seo if not r.get("has_canonical", False))
                print(f"\n  {C.BOLD}SEO Analysis ({len(seo)} pages){C.RST}")
                print(f"  ├─ Pages with issues:        {C.YELLOW}{total_issues}{C.RST}")
                print(f"  ├─ Missing <h1>:             {C.RED if no_h1 else C.GREEN}{no_h1}{C.RST}")
                print(f"  ├─ Missing meta description: {C.RED if no_desc else C.GREEN}{no_desc}{C.RST}")
                print(f"  └─ Missing canonical:        {C.RED if no_canonical else C.GREEN}{no_canonical}{C.RST}")

        if self._crawl_budget and self.aggregator.budget_exceeded_domains:
            print(f"\n  {C.BOLD}Crawl Budget{C.RST}")
            print(f"  └─ Domains at/exceeded cap: {len(self.aggregator.budget_exceeded_domains)}")

        if self.config.harvest and self._harvester:
            harvest_report = self._harvester.get_report()
            print(f"\n  {C.BOLD}Data Harvest Report{C.RST}")
            print(f"  ├─ Emails found:    {C.GREEN}{harvest_report['total_emails']}{C.RST}")
            print(f"  ├─ Phones found:    {C.YELLOW}{harvest_report['total_phones']}{C.RST}")
            print(f"  └─ Social handles:  {C.CYAN}{harvest_report['total_social']}{C.RST}")
            if harvest_report["emails"]:
                print(f"\n  {C.BOLD}Emails:{C.RST}")
                for email in harvest_report["emails"]:
                    print(f"    {C.DIM}•{C.RST} {email}")
            if harvest_report["phones"]:
                print(f"\n  {C.BOLD}Phones:{C.RST}")
                for phone in harvest_report["phones"]:
                    print(f"    {C.DIM}•{C.RST} {phone}")
            if harvest_report["social"]:
                print(f"\n  {C.BOLD}Social:{C.RST}")
                for platform, handles in harvest_report["social"].items():
                    for h in handles:
                        print(f"    {C.DIM}•{C.RST} {platform}: {h}")

        if self.config.secrets and self._secret_detector:
            findings = self._secret_detector.findings
            if findings:
                print(f"\n  {C.BOLD}Secrets Found ({len(findings)}){C.RST}")
                for f in findings[:20]:
                    print(f"  {C.RED}[{f['type']}]{C.RST} {f['value']} — {f['url'][:60]}")

        if self.config.wayback and self._wayback:
            print(f"\n  {C.BOLD}Wayback Machine{C.RST}")
            print(f"  ├─ Hits:  {C.GREEN}{self._wayback.hit_count}{C.RST}")
            print(f"  └─ Misses: {C.DIM}{self._wayback.miss_count}{C.RST}")

        if self.config.adaptive_delay and self._adaptive_delay:
            status = self._adaptive_delay.get_status()
            print(f"\n  {C.BOLD}Adaptive Delay{C.RST}")
            print(f"  ├─ Final delay: {status['current_delay']}s")
            print(f"  ├─ Error rate:  {status['error_rate']}")
            print(f"  └─ Samples:     {status['samples']}")

        if self.config.api_mode and self._api_crawler:
            endpoints = self._api_crawler.api_endpoints
            if endpoints:
                print(f"\n  {C.BOLD}API Endpoints ({len(endpoints)}){C.RST}")
                for ep in endpoints[:20]:
                    pag = " [paginated]" if ep["has_pagination"] else ""
                    print(f"  {C.CYAN}•{C.RST} {ep['url'][:80]}{pag}")

        if self.config.report_file:
            self.aggregator.save_report(self.config.report_file)
            print(f"  {C.GREEN}[+]{C.RST} Aggregation report saved to {self.config.report_file}")

        if self._out_fh:
            self._out_fh.flush()
            self._out_fh.close()
            print(f"  {C.GREEN}[+]{C.RST} URL list saved to {self.config.output_file}")

        if self._log_fh:
            self._log_fh.flush()
            self._log_fh.close()
            print(f"  {C.GREEN}[+]{C.RST} Log saved to {self.config.log_file}")

        if self._js_renderer:
            self._js_renderer.stop()

        print(f"  {C.CYAN}[*]{C.RST} Done. Total discovered: {self.total_discovered}")

    def _test_tor(self):
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
            print(f"  {C.DIM}    Make sure Tor service is running on {self.config.tor_proxy}{C.RST}")
            ans = input("\n  Continue without Tor? [y/N]: ").strip().lower()
            if ans != "y":
                sys.exit(1)
