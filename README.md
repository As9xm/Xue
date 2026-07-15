# Xue v4.0

Continuous internet crawler with Tor support, built-in aggregator, domain categorization, secrets detection, data harvesting, and enterprise-grade features.

Takes a seed URL, follows every link it finds, and keeps crawling until you hit CTRL+C. When you stop it, it prints a full aggregation report — domains visited, status code distribution, content types, domain categories, errors, largest pages, and more.

Supports clearnet and `.onion` sites seamlessly. If a clearnet page links to an onion service, the crawler follows it through Tor automatically.

## Install

```bash
pip install -e .

# Optional dependencies
pip install -e ".[all]"

# For JS rendering
playwright install chromium
```

## Usage

```bash
xue -u <URL> [options]

# Or as a module
python -m xue -u <URL> [options]
```

### Options

| Flag | Description | Default |
|---|---|---|
| `-u`, `--url` | Seed URL (required) | — |
| `-t`, `--threads` | Concurrent threads | 10 |
| `--auto` | Auto-detect optimal thread count | off |
| `-d`, `--delay` | Delay between requests per thread (seconds) | 0.5 |
| `-o`, `--output` | Save discovered URLs to file | — |
| `--format` | Output format: `txt`, `csv`, `jsonl` | `txt` |
| `-r`, `--report` | Save aggregation report as JSON | — |
| `--tor-proxy` | Tor SOCKS5 proxy address | `socks5h://127.0.0.1:9050` |
| `--timeout` | Request timeout (seconds) | 10 |
| `--max-depth` | Max crawl depth (0 = unlimited) | 0 |
| `--domains-only` | Only crawl root domains/subdomains | off |
| `-v`, `--verbose` | Show error details | off |
| `--respect-robots` | Respect robots.txt rules | on |
| `--no-robots` | Disable robots.txt checking | off |
| `--resume` | Checkpoint file to resume from | — |
| `--db` | SQLite database for persistent visited set | — |
| `--scope` | Restrict crawl to specific domain | — |
| `--exclude` | Regex patterns to exclude URLs (repeatable) | — |
| `--content-types` | Allowed MIME types (comma-separated) | all |
| `--log-file` | Structured JSON-lines log file | — |
| `--js` | Enable JavaScript rendering for SPA pages | off |
| `--checkpoint-interval` | Auto-save checkpoint every N pages | 500 |
| `--proxy-list` | File with proxy list (one per line) | — |
| `--proxy-api` | API URL to fetch proxies from | — |
| `--dedup` | Detect duplicate pages via SimHash fingerprinting | off |
| `--graph` | Export crawl graph to file | — |
| `--graph-format` | Graph export format: `json`, `dot`, `gexf` | `json` |
| `--secrets` | Scan for leaked secrets/credentials | off |
| `--harvest` | Harvest emails, phones, social handles | off |
| `--wayback` | Lookup 404s in Wayback Machine | off |
| `--adaptive-delay` | Auto-tune delay based on error rate | off |
| `--api-mode` | Detect and report API endpoints | off |
| `--redis` | Redis URL for distributed crawl queue | — |
| `--plugins` | Directory containing plugin `.py` files | — |

### Examples

```bash
xue -u https://example.com
xue -u https://example.com --auto -d 0.2 -o urls.txt -r report.json
xue -u https://example.com --secrets --harvest
xue -u https://example.com --graph graph.json --graph-format dot
xue -u https://example.com --dedup --adaptive-delay
xue -u https://example.com --redis redis://localhost:6379
```

## Features

### Core
- **Multi-threaded crawl** — ThreadPoolExecutor with configurable concurrency
- **Tor / .onion support** — Auto-detects and routes `.onion` URLs through SOCKS5
- **UA rotation + header randomization** — 15 real browser UAs with full `Sec-CH-UA` headers
- **Domain categorization** — 16 categories based on domain name + page title
- **System profiler + auto-threads** — CPU/RAM-aware thread count recommendation

### Politeness
- **robots.txt** — Fetches and respects rules per domain with TTL cache
- **Per-domain rate limiting** — Tracks last-request-time per domain
- **Retry-After** — Backs off and re-enqueues on 429/503 with `Retry-After` header

### Resumability
- **Checkpoints** — Auto-saves on CTRL+C and every N pages. Resume with `--resume`
- **SQLite backend** — Persistent visited set + queue via `--db xue.db`

### Crawl Quality
- **URL scope** — `--scope example.com` restricts to specific domains
- **URL denylist** — `--exclude` regex patterns (repeatable)
- **Content-type filtering** — `--content-types` MIME whitelist
- **Sitemap discovery** — Auto-discovers `/sitemap.xml`

### Advanced
- **Proxy rotation pool** — Load proxies from file/API, rotate per-request with health tracking
- **SimHash dedup** — Near-duplicate page detection via 64-bit SimHash
- **Secret detection** — Scans HTML for AWS keys, GitHub tokens, Stripe keys, JWTs
- **Data harvesting** — Extracts emails, phone numbers, social media handles
- **Wayback Machine** — Lookup archived versions of 404 pages
- **Adaptive delay** — Auto-tunes request delay based on real-time error rate
- **API detection** — Identifies JSON API endpoints and pagination patterns
- **Graph export** — Full crawl graph as JSON, DOT (Graphviz), GEXF (Gephi)
- **Redis queue** — Distributed crawl queue for multi-instance crawls
- **Plugin system** — Hook into crawl events via Python plugins
- **JS rendering** — Playwright-based JavaScript rendering for SPAs

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check xue/
mypy xue/
```

## REST API (Coming in v4.1)

Xue will expose a FastAPI-based REST API and Web UI for managing crawls remotely.

## Project Structure

```
xue/
├── __init__.py        # Package init
├── __main__.py        # Entry point
├── cli.py             # CLI (argparse)
├── config.py          # CrawlerConfig dataclass
├── crawler.py         # Main crawl engine
├── aggregator.py      # Stats collection + reporting
├── profiler.py        # System profiler
├── classifier.py      # Domain categorization
├── robots.py          # robots.txt manager
├── sqlite_store.py    # SQLite persistence
├── sitemap.py         # Sitemap parsing
├── proxy_pool.py      # Proxy rotation
├── fingerprint.py     # SimHash dedup
├── secret_detector.py # Secret scanning
├── harvester.py       # Data harvesting
├── wayback.py         # Wayback Machine lookup
├── api_crawl.py       # API detection
├── graph_export.py    # Graph export
├── adaptive_delay.py  # Auto-tuning delay
├── plugin.py          # Plugin system
├── redis_queue.py     # Redis queue
├── js_renderer.py     # Playwright JS renderer
├── models.py          # Pydantic models
└── api/               # FastAPI routes (WIP)
```
