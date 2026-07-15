import argparse
import sys
from urllib.parse import urlparse

from xue.ansi import C
from xue.config import CrawlerConfig
from xue.crawler import XueCrawler


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xue",
        description="Xue v4.0 — Continuous Internet Crawler with Tor, Secrets Detection, Data Harvesting & More",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  xue -u https://example.com
  xue -u https://example.com --auto -d 0.2 -o urls.txt -r report.json
  xue -u https://example.com --secrets --harvest
  xue -u https://example.com --graph graph.json --graph-format dot
  xue -u https://example.com --dedup --adaptive-delay
  xue -u https://example.com --proxy-list proxies.txt
  xue -u https://example.com --redis redis://localhost:6379
  xue -u https://example.com --api-mode --wayback
  xue -u https://example.com --plugins ./plugins
        """
    )

    parser.add_argument("-u", "--url", required=True, help="Seed URL to start crawling")
    parser.add_argument("-t", "--threads", type=int, default=10, help="Concurrent threads (default: 10)")
    parser.add_argument("--auto", action="store_true", dest="auto_threads", help="Auto-detect optimal thread count")
    parser.add_argument("-d", "--delay", type=float, default=0.5, help="Delay between requests (seconds)")
    parser.add_argument("-o", "--output", help="File to save discovered URLs")
    parser.add_argument("--format", default="txt", choices=["txt", "csv", "jsonl"], help="Output format (default: txt)")
    parser.add_argument("-r", "--report", help="Save aggregation report as JSON")
    parser.add_argument("--tor-proxy", default="socks5h://127.0.0.1:9050", help="Tor SOCKS5 proxy")
    parser.add_argument("--timeout", type=int, default=10, help="Request timeout (seconds)")
    parser.add_argument("--max-depth", type=int, default=0, help="Max crawl depth (0 = unlimited)")
    parser.add_argument("--domains-only", action="store_true", help="Only crawl root domains/subdomains")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose error output")
    parser.add_argument("--respect-robots", action="store_true", default=True, help="Respect robots.txt (default: on)")
    parser.add_argument("--no-robots", action="store_true", help="Disable robots.txt checking")
    parser.add_argument("--resume", help="Checkpoint file to resume from")
    parser.add_argument("--db", help="SQLite database for persistent visited set")
    parser.add_argument("--scope", help="Restrict crawl to specific domain")
    parser.add_argument("--exclude", action="append", default=[], help="Regex patterns to exclude URLs")
    parser.add_argument("--content-types", help="Allowed MIME types (comma-separated)")
    parser.add_argument("--log-file", help="Structured JSON-lines log file")
    parser.add_argument("--js", action="store_true", help="Enable JavaScript rendering for SPAs")
    parser.add_argument("--checkpoint-interval", type=int, default=500, help="Auto-save checkpoint every N pages")

    parser.add_argument("--proxy-list", help="File with proxy list (one per line)")
    parser.add_argument("--proxy-api", help="API URL to fetch proxies from")
    parser.add_argument("--dedup", action="store_true", help="Detect duplicate pages via SimHash")
    parser.add_argument("--graph", help="Export crawl graph to file")
    parser.add_argument("--graph-format", default="json", choices=["json", "dot", "gexf"], help="Graph export format")
    parser.add_argument("--secrets", action="store_true", help="Scan for leaked secrets/credentials")
    parser.add_argument("--harvest", action="store_true", help="Harvest emails, phones, social handles")
    parser.add_argument("--wayback", action="store_true", help="Lookup 404s in Wayback Machine")
    parser.add_argument("--adaptive-delay", action="store_true", help="Auto-tune delay based on error rate")
    parser.add_argument("--plugins", help="Directory containing plugin .py files")
    parser.add_argument("--broken-links", action="store_true", dest="broken_links_only", help="Report broken links only")
    parser.add_argument("--api-mode", action="store_true", help="Detect and report API endpoints")
    parser.add_argument("--redis", help="Redis URL for distributed crawl queue")

    # Phase 2
    parser.add_argument("--strategy", default="bfs", choices=["bfs", "dfs", "priority"],
                        help="Crawl order strategy (default: bfs)")
    parser.add_argument("--no-normalize", action="store_true", help="Disable URL normalization")
    parser.add_argument("--max-pages-per-domain", type=int, default=0,
                        help="Max pages per domain (0 = unlimited)")
    parser.add_argument("--max-time-per-domain", type=int, default=0,
                        help="Max seconds per domain (0 = unlimited)")
    parser.add_argument("--max-size-per-domain", type=int, default=0,
                        help="Max bytes per domain (0 = unlimited)")
    parser.add_argument("--tech-fingerprint", action="store_true",
                        help="Detect CMS/framework technologies")
    parser.add_argument("--extract-content", action="store_true",
                        help="Extract clean article text from pages")
    parser.add_argument("--seo", action="store_true", dest="seo_analysis",
                        help="Analyze SEO meta tags and heading structure")

    return parser


def config_from_args(args) -> CrawlerConfig:
    respect_robots = args.respect_robots and not args.no_robots
    return CrawlerConfig(
        seed_url=args.url,
        threads=args.threads,
        delay=args.delay,
        timeout=args.timeout,
        tor_proxy=args.tor_proxy,
        output_file=args.output,
        output_format=args.format,
        max_depth=args.max_depth,
        verbose=args.verbose,
        report_file=args.report,
        domains_only=args.domains_only,
        auto_threads=args.auto_threads,
        respect_robots=respect_robots,
        resume_checkpoint=args.resume,
        db_path=args.db,
        scope=args.scope,
        exclude_patterns=args.exclude,
        content_types=args.content_types,
        log_file=args.log_file,
        js_render=args.js,
        checkpoint_interval=args.checkpoint_interval,
        proxy_file=args.proxy_list,
        proxy_api=args.proxy_api,
        dedup=args.dedup,
        graph_file=args.graph,
        graph_format=args.graph_format,
        secrets=args.secrets,
        harvest=args.harvest,
        wayback=args.wayback,
        adaptive_delay=args.adaptive_delay,
        plugin_dir=args.plugins,
        broken_links_only=args.broken_links_only,
        api_mode=args.api_mode,
        redis_url=args.redis,
        crawl_strategy=args.strategy,
        normalize_urls=not args.no_normalize,
        max_pages_per_domain=args.max_pages_per_domain,
        max_time_per_domain=args.max_time_per_domain,
        max_size_per_domain=args.max_size_per_domain,
        tech_fingerprint=args.tech_fingerprint,
        extract_content=args.extract_content,
        seo_analysis=args.seo_analysis,
    )


def main():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    parser = create_parser()
    args = parser.parse_args()

    parsed = urlparse(args.url)
    if parsed.scheme not in ("http", "https"):
        print(f"  {C.RED}[!]{C.RST} Invalid URL scheme. Use http:// or https://")
        sys.exit(1)
    if not parsed.netloc:
        print(f"  {C.RED}[!]{C.RST} Invalid URL. Must include a domain.")
        sys.exit(1)

    config = config_from_args(args)
    crawler = XueCrawler(config)
    crawler.run()


if __name__ == "__main__":
    main()
