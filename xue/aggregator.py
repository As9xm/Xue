import collections
import heapq
import json
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from xue.ansi import C
from xue.classifier import DomainClassifier


class Aggregator:
    def __init__(self):
        self._lock = threading.Lock()
        self.domains = collections.Counter()
        self.domain_first_seen = {}
        self.status_codes = collections.Counter()
        self.content_types = collections.Counter()
        self.total_links_found = 0
        self.total_size_bytes = 0
        self.errors = collections.Counter()
        self.error_urls = collections.deque(maxlen=200)
        self.onion_count = 0
        self.clearnet_count = 0
        self.classifier = DomainClassifier()
        self.domain_categories = collections.defaultdict(list)
        self.domain_to_category = {}
        self.start_time = time.time()
        self.largest_pages = []
        self.robots_blocked = 0
        self.retry_after_count = 0
        self.api_endpoints_found = 0
        self.broken_links = []
        self.duplicate_pages = 0
        self.tech_findings: dict[str, list[dict]] = {}
        self.content_stats = {"pages_extracted": 0, "total_words": 0, "total_chars": 0}
        self.seo_reports: list[dict] = []
        self.budget_exceeded_domains: list[str] = []

    def record_page(self, url, status_code, content_type, links_found, depth, size_bytes=0, title=""):
        with self._lock:
            parsed = urlparse(url)
            domain = parsed.netloc
            self.domains[domain] += 1
            if domain not in self.domain_first_seen:
                self.domain_first_seen[domain] = datetime.now().isoformat()
            if domain not in self.domain_to_category:
                cat = self.classifier.classify(domain, title)
                self.domain_to_category[domain] = cat
                self.domain_categories[cat].append(domain)
            self.status_codes[status_code] += 1
            ct = (content_type or "unknown").split(";")[0].strip()
            self.content_types[ct] += 1
            self.total_links_found += links_found
            self.total_size_bytes += size_bytes
            if domain.endswith(".onion"):
                self.onion_count += 1
            else:
                self.clearnet_count += 1
            if len(self.largest_pages) < 10:
                heapq.heappush(self.largest_pages, (size_bytes, url))
            else:
                heapq.heappushpop(self.largest_pages, (size_bytes, url))
            if status_code >= 400:
                self.broken_links.append({"url": url, "status": status_code, "source": ""})
                if len(self.broken_links) > 500:
                    self.broken_links = self.broken_links[-500:]
            if "application/json" in ct:
                self.api_endpoints_found += 1

    def record_error(self, url, error_msg):
        with self._lock:
            error_type = type(error_msg).__name__ if not isinstance(error_msg, str) else error_msg.split(":")[0]
            self.errors[error_type] += 1
            self.error_urls.append((url, str(error_msg)))

    def record_robots_blocked(self):
        with self._lock:
            self.robots_blocked += 1

    def record_retry_after(self):
        with self._lock:
            self.retry_after_count += 1

    def record_duplicate(self):
        with self._lock:
            self.duplicate_pages += 1

    def record_tech_findings(self, url: str, findings: list):
        with self._lock:
            domain = urlparse(url).netloc
            if domain not in self.tech_findings:
                self.tech_findings[domain] = []
            for f in findings:
                self.tech_findings[domain].append({
                    "name": f.name,
                    "confidence": f.confidence,
                    "evidence": f.evidence,
                })

    def record_content(self, url: str, extracted):
        with self._lock:
            self.content_stats["pages_extracted"] += 1
            self.content_stats["total_words"] += extracted.word_count
            self.content_stats["total_chars"] += extracted.char_count

    def record_seo(self, report):
        with self._lock:
            self.seo_reports.append({
                "url": report.url,
                "title": report.title,
                "title_length": report.title_length,
                "meta_description": report.meta_description,
                "h1_count": report.h1_count,
                "has_canonical": report.has_canonical,
                "images_without_alt": report.images_without_alt,
                "issues": report.heading_issues,
            })

    def record_budget_exceeded(self, url: str):
        with self._lock:
            domain = urlparse(url).netloc
            if domain not in self.budget_exceeded_domains:
                self.budget_exceeded_domains.append(domain)

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
        with self._lock:
            elapsed = time.time() - self.start_time
            total = sum(self.status_codes.values())
            return {
                "summary": {
                    "total_pages_crawled": total,
                    "total_unique_domains": len(self.domains),
                    "total_errors": sum(self.errors.values()),
                    "robots_blocked": self.robots_blocked,
                    "retry_after_count": self.retry_after_count,
                    "duplicate_pages": self.duplicate_pages,
                    "api_endpoints_found": self.api_endpoints_found,
                    "broken_links_count": len(self.broken_links),
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
                "largest_pages": sorted(self.largest_pages, key=lambda x: x[0], reverse=True),
                "broken_links": self.broken_links[-50:],
            }

    def save_report(self, filepath):
        report = self.generate_report()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        return filepath

    def print_summary(self):
        report = self.generate_report()
        s = report["summary"]
        print(f"\n{'='*60}")
        print(f"{C.CYAN}{C.BOLD}  AGGREGATION REPORT{C.RST}")
        print(f"{'='*60}")
        print(f"\n  {C.BOLD}Overview{C.RST}")
        print(f"  ├─ Pages crawled:      {C.GREEN}{s['total_pages_crawled']}{C.RST}")
        print(f"  ├─ Unique domains:     {C.BLUE}{s['total_unique_domains']}{C.RST}")
        print(f"  ├─ Clearnet pages:     {C.WHITE}{s['clearnet_pages']}{C.RST}")
        print(f"  ├─ Onion pages:        {C.MAGENTA}{s['onion_pages']}{C.RST}")
        print(f"  ├─ Errors:             {C.RED}{s['total_errors']}{C.RST}")
        if s.get('robots_blocked', 0) > 0:
            print(f"  ├─ Robots blocked:     {C.YELLOW}{s['robots_blocked']}{C.RST}")
        if s.get('retry_after_count', 0) > 0:
            print(f"  ├─ Retry-After hits:   {C.YELLOW}{s['retry_after_count']}{C.RST}")
        if s.get('duplicate_pages', 0) > 0:
            print(f"  ├─ Duplicate pages:    {C.DIM}{s['duplicate_pages']}{C.RST}")
        if s.get('api_endpoints_found', 0) > 0:
            print(f"  ├─ API endpoints:      {C.CYAN}{s['api_endpoints_found']}{C.RST}")
        if s.get('broken_links_count', 0) > 0:
            print(f"  ├─ Broken links:       {C.RED}{s['broken_links_count']}{C.RST}")
        print(f"  ├─ Data downloaded:    {s['total_data_downloaded_mb']} MB")
        print(f"  ├─ Links found:        {s['total_links_found']}")
        print(f"  ├─ Duration:           {s['crawl_duration']}")
        print(f"  └─ Speed:              {s['pages_per_second']} pages/sec")
        if report["status_code_distribution"]:
            print(f"\n  {C.BOLD}Status Codes{C.RST}")
            for code, count in sorted(report["status_code_distribution"].items()):
                color = C.GREEN if 200 <= code < 300 else C.YELLOW if 300 <= code < 400 else C.RED
                print(f"    {color}{code}{C.RST}: {count}")
        if report["top_domains"]:
            print(f"\n  {C.BOLD}Top Domains (by pages){C.RST}")
            for i, (domain, count) in enumerate(report["top_domains"][:15], 1):
                marker = f"{C.MAGENTA}[TOR]{C.RST} " if domain.endswith(".onion") else ""
                print(f"    {C.DIM}{i:>3}.{C.RST} {marker}{domain} — {C.CYAN}{count}{C.RST} pages")
        if report["domains_by_category"]:
            print(f"\n  {C.BOLD}Domains by Category{C.RST}")
            cat_colors = {
                "Pornography / Adult": C.RED, "Social Media": C.BLUE, "Gaming": C.GREEN,
                "Game Store / Marketplace": C.GREEN, "Technology": C.CYAN, "News / Media": C.YELLOW,
                "Forums / Community": C.MAGENTA, "Shopping / E-Commerce": C.YELLOW,
                "Streaming / Entertainment": C.MAGENTA, "Education": C.CYAN, "Government": C.WHITE,
                "Finance / Crypto": C.GREEN, "AI / Machine Learning": C.CYAN,
                "Search Engine": C.BLUE, "Advertising / Tracking": C.GRAY, "Uncategorized": C.DIM,
            }
            for cat, domains in report["domains_by_category"].items():
                color = cat_colors.get(cat, C.DIM)
                print(f"\n    {color}{C.BOLD}{cat}{C.RST} ({len(domains)} domains)")
                for d in domains[:8]:
                    print(f"      {C.DIM}•{C.RST} {d}")
                if len(domains) > 8:
                    print(f"      {C.DIM}  ... and {len(domains) - 8} more{C.RST}")
        if report["content_type_distribution"]:
            print(f"\n  {C.BOLD}Content Types{C.RST}")
            for ct, count in list(report["content_type_distribution"].items())[:10]:
                print(f"    {C.DIM}•{C.RST} {ct}: {count}")
        if report["error_distribution"]:
            print(f"\n  {C.BOLD}Error Types{C.RST}")
            for err, count in list(report["error_distribution"].items())[:10]:
                print(f"    {C.RED}•{C.RST} {err}: {count}")
        if report.get("broken_links"):
            print(f"\n  {C.BOLD}Broken Links (4xx/5xx){C.RST}")
            for bl in report["broken_links"][:10]:
                print(f"    {C.RED}{bl['status']}{C.RST} {bl['url'][:80]}")
        if report["largest_pages"]:
            print(f"\n  {C.BOLD}Largest Pages{C.RST}")
            for size, url in report["largest_pages"][:5]:
                size_kb = size / 1024 if size else 0
                print(f"    {C.DIM}•{C.RST} {size_kb:.1f} KB — {url[:80]}")
        print(f"\n{'='*60}\n")
