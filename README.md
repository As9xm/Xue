# Xue

Continuous internet crawler with Tor support, built-in aggregator, and domain categorization.

Takes a seed URL, follows every link it finds, and keeps crawling until you hit CTRL+C. When you stop it, it prints a full aggregation report — domains visited, status code distribution, content types, domain categories, errors, largest pages, and more.

Supports clearnet and `.onion` sites seamlessly. If a clearnet page links to an onion service, the crawler follows it through Tor automatically.

## Install

```
pip install -r requirements.txt
```

Dependencies: `requests`, `beautifulsoup4`, `PySocks`, `psutil`

For Tor support, you need the Tor service running locally (default: `127.0.0.1:9050`).

## Usage

```
python xue.py -u <URL> [options]
```

### Options

| Flag | Description | Default |
|---|---|---|
| `-u`, `--url` | Seed URL (required) | — |
| `-t`, `--threads` | Concurrent threads | 10 |
| `--auto` | Auto-detect optimal thread count based on system specs | off |
| `-d`, `--delay` | Delay between requests per thread (seconds) | 0.5 |
| `-o`, `--output` | Save discovered URLs to file | — |
| `-r`, `--report` | Save aggregation report as JSON | — |
| `--tor-proxy` | Tor SOCKS5 proxy address | `socks5h://127.0.0.1:9050` |
| `--timeout` | Request timeout (seconds) | 10 |
| `--max-depth` | Max crawl depth (0 = unlimited) | 0 |
| `--domains-only` | Only crawl root domains/subdomains, skip individual pages | off |
| `-v`, `--verbose` | Show error details | off |

### Examples

```bash
# Basic crawl
python xue.py -u https://example.com

# Auto-detect threads, save URLs and report
python xue.py -u https://example.com --auto -d 0.2 -o urls.txt -r report.json

# High thread count manual
python xue.py -u https://example.com -t 50 -d 0.3

# Domain discovery mode — only crawl new domains, skip endpoints
python xue.py -u https://example.com --auto --domains-only

# Crawl an onion service
python xue.py -u http://someonion.onion -v

# Limit depth to 3 levels
python xue.py -u https://example.com --max-depth 3
```

## Features

### System Profiler

On startup, Xue detects your system specs (CPU cores, RAM, current CPU usage) and prints a recommended thread count. Use `--auto` to let it pick the optimal count automatically. If you manually set `-t` above the safe limit, it warns you and falls back to the recommended count.

Uses `psutil` for accurate detection when available, falls back to OS-level detection otherwise.

### Domains-Only Mode

With `--domains-only`, the crawler still extracts all links from every page, but instead of queueing every endpoint it finds, it only queues the root URL of each newly discovered domain or subdomain. This turns Xue into a domain discovery engine — useful for mapping out what domains a site links to across the web.

### Domain Categorization

The aggregator classifies every domain it encounters into categories based on keyword matching against the domain name:

- Pornography / Adult
- Social Media
- Gaming
- Game Store / Marketplace
- Technology
- News / Media
- Forums / Community
- Shopping / E-Commerce
- Streaming / Entertainment
- Education
- Government
- Finance / Crypto
- AI / Machine Learning
- Search Engine
- Advertising / Tracking
- Uncategorized

Categories appear in the final report and in the JSON export.

### Anti-Detection

To reduce 403 blocks from sites that filter bots:

- Rotates through a pool of 15 real browser User-Agent strings (Chrome, Firefox, Edge, Safari across Windows, Mac, Linux)
- Sends full browser-like headers on every request: `Sec-Fetch-*`, `Sec-CH-UA`, `DNT`, `Upgrade-Insecure-Requests`, `Referer`
- UA and headers are randomized per request to avoid fingerprinting

### Aggregation Report

When you stop the crawler (CTRL+C), it prints:

- Total pages crawled and unique domains
- Clearnet vs onion page breakdown
- Status code distribution (2xx, 3xx, 4xx, 5xx)
- Top domains by page count
- Domains sorted by category
- Content type distribution
- Error breakdown
- Largest pages by size
- Crawl speed (pages/sec) and duration

Use `-r report.json` to save the full report as JSON.

### Performance

- Multi-threaded via `ThreadPoolExecutor`
- Connection pooling (`HTTPAdapter`) sized to thread count for TCP reuse
- `SoupStrainer` — only parses `<a>` tags instead of the full DOM
- `stream=True` with 10 MB body cap to prevent memory blowout
- Bounded deques for error tracking
- Print locks for clean output under concurrency

## Tor Setup

**Windows**: Download the Tor Expert Bundle from [torproject.org](https://www.torproject.org/download/tor/) and run `tor.exe`.

**Linux/Mac**:
```bash
sudo apt install tor   # Debian/Ubuntu
brew install tor       # macOS
tor                    # Start the service
```

The crawler auto-detects `.onion` URLs and routes them through the SOCKS5 proxy. Clearnet URLs go direct.

## Rust Version

A Rust port is in progress under `xue-rs/`. It uses `tokio`, `reqwest`, `scraper`, and `clap` for true async concurrency without a GIL. Not yet complete — use the Python version for now.
